# Multi-turn Dialogue Assistant Based on AI Agent Session

This case demonstrates how to build an intelligent dialogue assistant that supports multi-turn interaction by leveraging openYuanrong's AI Agent Session capability. Through `waitForNotify` and `notify` mechanisms, functions can suspend execution and wait for user input during execution, thereby implementing complex interaction logic.

## Scenario Description

In traditional FaaS models, functions are typically trigger-based execution and "run-to-completion". For multi-turn dialogue scenarios, developers usually need to manage complex context states themselves (such as Redis or databases).

openYuanrong's AI Agent Session feature provides the following advantages:

- **Automatic State Management**: Session context is automatically persisted and loaded with the session lifecycle.
- **Execution Flow Suspension**: Supports suspension within functions via `waitForNotify`, waiting for subsequent requests from the same session to wake up.
- **Low-latency Response**: Through session affinity scheduling, ensures requests from the same session are routed to the same instance, reducing cold start and state synchronization overhead.

## Development Steps

### 1. Enable Function Session Feature

When registering the function, set `enableAgentSession` to `true`.

```bash
# Register using yr command line tool or REST API
curl -X POST http://{meta_service}/serverless/v1/functions \
-H "Content-Type: application/json" \
-d '{
    "name": "0@ai@dialogue-agent",
    "runtime": "java8",
    "handler": "org.example.DialogueAgent.handle",
    "enableAgentSession": true,
    "cpu": 1000,
    "memory": 1024
}'
```

### 2. Write Function Logic (Java)

Implement a simple multi-turn Q&A logic using Java SDK.

```java
package org.example;

import org.yuanrong.services.Context;
import org.yuanrong.services.session.Session;
import org.yuanrong.services.session.SessionService;
import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.List;

public class DialogueAgent {
    public Object handle(Context ctx, JsonObject input) {
        SessionService sessService = ctx.getSessionService();
        Session sess = sessService.loadSession(ctx.getSessionId());

        // 1. If it's a notify request (triggered by subsequent calls), execute wake-up logic
        if (input.has("action") && "notify".equals(input.get("action").getAsString())) {
            sess.notify(input.getAsJsonObject("payload"));
            return null; // Notify request does not return results to the current trigger
        }

        // 2. Main session execution flow
        try {
            // First round
            ctx.getStream().write("Hello! I'm your AI assistant. What should I call you?\n");
            JsonObject nameInput = sess.waitForNotify(60000); // Suspend and wait for input, timeout 60s
            if (nameInput == null) return "Timeout waiting for name";
            
            String userName = nameInput.get("message").getAsString();
            
            // Update session history
            List<String> history = new ArrayList<>(sess.getHistories());
            history.add("User Name: " + userName);
            sess.setHistories(history);

            // Second round
            ctx.getStream().write(userName + ", nice to meet you! How can I help you today?\n");
            JsonObject taskInput = sess.waitForNotify(60000);
            if (taskInput == null) return "Timeout waiting for task instruction";

            String task = taskInput.get("message").getAsString();
            ctx.getStream().write("OK, processing your task: " + task + "...\n");
            
            // Simulate task processing...
            Thread.sleep(2000);
            
            ctx.getStream().write("Processing complete! Goodbye, " + userName + ".");

        } catch (Exception e) {
            ctx.getLogger().log("Error: " + e.getMessage());
        }

        return "Session Finished";
    }
}
```

## Client Interaction Flow

Step A: Start session and begin first round

1. **Client**: Call `POST /invocations` (SessionID: S1)
2. **Gateway**: Forward request to bound instance
3. **Function Instance**: Execute business logic and enter `sess.waitForNotify()`, execution thread suspends

Step B: Send notification data for wake-up

1. **Client**: Call `POST /invocations` (Same SessionID, Action: notify)
2. **Gateway**: Distribute request to the same instance (session affinity)
3. **Function Instance**: Execute `sess.notify(payload)`, wake up previously suspended thread
4. **Function Instance**: Return Notify operation success response to gateway

Wake-up and Final Response

1. **Function Instance**: Original thread successfully wakes up, obtains data and continues processing subsequent logic
2. **Function Instance**: Complete all processing logic, return final result of first round request to client

## Summary

Through AI Agent Session, developers can write multi-turn interaction logic as if writing a single-machine synchronous program, greatly simplifying the complexity of distributed context management. Combined with openYuanrong's session affinity scheduling, the system can efficiently handle notification requests, ensuring interaction real-time performance.
