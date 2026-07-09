# AI Agent Sessions and Affinity Scheduling

The AI Agent session feature is designed for interactive application scenarios (such as AI agents, multi-turn conversations). It supports active waiting and external wake-up during function execution, and ensures that multiple requests within the same session can be routed to the same execution instance, achieving low-latency interactive experiences.

## Session Scheduling Mechanism

The AI Agent session scheduling logic is handled by the `faasscheduler` module, with the following core features:

### 1. Session Affinity

When a request carries a `sessionId`, the scheduling system will attempt to route it to the instance already bound to that session.

- **First Request**: The scheduling system selects an appropriate instance and establishes the binding relationship between `sessionId` and `instanceId`.
- **Subsequent Requests**: As long as the binding relationship is valid, all requests with the same `sessionId` will be directed to the same instance.

### 2. Weak Affinity and Persistence

AI Agent sessions default to weak affinity (`TTL` is ``0``).

- **Lifecycle**: When all leases under a session are released, the binding relationship may become invalid.
- **State Recovery**: Session context data (such as history records) is persisted in a distributed data system. When a new request arrives and the original instance is unavailable, a new instance will reload the session state from the data system.

## SDK Usage Instructions

In functions with AI Agent sessions enabled, you can obtain the `SessionService` through `Context` to operate session objects.

### Java SDK

#### Core Interface: Session

The `Session` object provides capabilities for in-session synchronization and state management.

- **`wait(long timeoutMs)`**: Suspend the current execution thread, waiting for input.
- **`notify(JsonObject payload)`**: Wake up a thread that is `wait`ing.
- **`getInterrupted()`**: Check whether the current session has been externally interrupted.

#### Java Usage Example

```java
import com.google.gson.JsonObject;

public Object handle(Context ctx, JsonObject input) {
    Session sess = ctx.getSessionService().loadSession(ctx.getSessionId());

    // Check if this is a notify request, assuming the user passes notification content in the payload field
    if (input.has("action") && "notify".equals(input.get("action").getAsString())) {
        sess.notify(input.getAsJsonObject("payload"));
        return "Notified";
    }

    JsonObject userInput = sess.wait(60000);
    
    if (userInput == null) return "Timeout";
    if (sess.getInterrupted()) return "Interrupted";
    
    return "Got: " + userInput.toString();
}
```

### Python SDK

In Python function instances, the `yr` module provides similar session operation capabilities.

#### Core Interface: `yr.SessionService`

- **`session.wait_for_notify(timeout_ms)`**: Block the current coroutine/thread, waiting for notification.
- **`session.notify(payload)`**: Send notification.
- **`session.is_interrupted()`**: Check whether the session has been interrupted.

#### Python Usage Example

```python
import yr

def handle(ctx, input):
    session_id = ctx.get_session_id()
    session = ctx.get_session_service().load_session(session_id)

    if input.get("action") == "notify":
        session.notify(input.get("payload"))
        return "Notified"

    # Wait for notification
    user_input = session.wait_for_notify(60000)
    
    if user_input is None:
        return "Wait timeout"
        
    if session.is_interrupted():
        return "Session Interrupted"
        
    return f"Received: {user_input}"
```

## Complete Use Case: Multi-Turn Conversation AI Agent

The following is a complete Java example demonstrating how to use `wait`/`notify` to implement a simple multi-turn interaction.

```java
import org.yuanrong.services.Context;
import org.yuanrong.services.session.Session;
import org.yuanrong.services.session.SessionService;
import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.List;

public class SimpleAgent {
    public Object handle(Context ctx, JsonObject input) {
        SessionService sessService = ctx.getSessionService();
        Session sess = sessService.loadSession(ctx.getSessionId());

        // 1. Handle notification/wake-up request
        if (input.has("action") && "notify".equals(input.get("action").getAsString())) {
            // Extract the actual notification payload for wake-up
            sess.notify(input.getAsJsonObject("payload"));
            return null; // Notify requests typically don't need to return business results
        }

        // 2. Main execution flow
        try {
            ctx.getLogger().log("Agent Started, SessionID: " + ctx.getSessionId());
            
            // First round of interaction
            ctx.getStream().write("Hello! I'm an AI assistant, how can I help you?\n");
            JsonObject input1 = sess.wait(30000); // Wait for user input for 30 seconds
            if (input1 == null) return "Wait timeout";
            
            String msg1 = input1.get("message").getAsString();
            ctx.getStream().write("Received command: " + msg1 + "\nProcessing for you...\n");
            
            // Simulate processing and update history
            List<String> history = new ArrayList<>(sess.getHistories());
            history.add("User: " + msg1);
            sess.setHistories(history);
            
            // Second round of interaction
            ctx.getStream().write("Processing completed. Do you have any other questions?\n");
            JsonObject input2 = sess.wait(30000);
            if (input2 == null) return "Wait timeout";

            if (sess.getInterrupted()) {
                return "Session has been externally interrupted";
            }

            String msg2 = input2.get("message").getAsString();
            ctx.getStream().write("Okay, received your further request: " + msg2 + "\n");

        } catch (Exception e) {
            ctx.getLogger().log("Error: " + e.getMessage());
        }

        return "Session Completed";
    }
}
```

### Interaction Flow Diagram

First round of interaction: Logical suspension

1. **Client** initiates `POST /invocations` (carrying `SessionID`: ``S1``)
2. **Function Instance** receives the request, executes business logic, until calling `sess.wait()`
3. **Function Instance** releases the session lock, execution thread enters suspended state, waiting for wake-up

Second round of interaction: Wake-up and continuation

1. **Client** initiates a second request `POST /invocations` (same `SessionID`: ``S1``, `Action`: ``notify``)
2. **Function Instance** receives the request, due to session affinity, the request enters the same instance
3. **Function Instance** executes `sess.notify(payload)`, waking up the previously suspended thread
4. **Function Instance** completes processing the notify request and returns ``200 OK``
5. **Function Instance** (original thread) obtains the data passed by `notify`, continues executing subsequent logic
6. **Function Instance** (original thread) completes processing, returns the final result of the first round request to the client
