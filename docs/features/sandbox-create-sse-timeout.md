# Sandbox Create Timeout and SSE Result Delivery Design

## Problem statement

`sandbox-sdk` exposes `Sandbox(...)` and `POST /api/sandbox/v1/sandboxes` as
synchronous create operations: once the call succeeds, users expect the sandbox
to be ready. The previous implementation had several conflicting timeout
semantics:

1. **The SDK HTTP timeout differed from the frontend/librt create timeout.**
   - The SDK could wait longer than the internal frontend/librt create timeout.
   - After the frontend timed out internally, the SDK could still receive a
     successful response instead of the final create result.

2. **The frontend could treat an unconfirmed timeout as a successful create.**
   - When librt returned `3002 create instance timeout` with an `instanceID`, the
     frontend could downgrade the timeout to success.
   - If rootfs preparation, image pulling, or runtime startup later failed, the
     SDK had already received `200 + status=running`, so the actual failure could
     not be reported.
   - A typical symptom was `image="python3.12-slim"` failing to start after the
     SDK had already reported success, with a later reverse-tunnel request
     exposing the failure as a 404 or timeout.

3. **An intermediate EIP, load balancer, or ingress may enforce a 30- or
   90-second HTTP idle timeout.**
   - Even if the logical create timeout is aligned at 120 or 300 seconds, an
     intermediate network device may close a long, silent HTTP POST.
   - The create protocol therefore cannot rely on one silent POST blocking until
     completion.

The goal is to use one logical create budget from the SDK through HTTP,
frontend, librt, and the runtime, while never reporting success before the
instance is confirmed as Running.

## Design

### 1. Align the logical create budget

Define an end-to-end create budget, for example:

```text
YR_SANDBOX_CREATE_TIMEOUT=120
```

The SDK exposes the total create budget and also allows callers to specify the
scheduling budget directly:

```python
Sandbox(..., create_timeout=120)
# Alternatively: Sandbox(..., schedule_timeout=90)
```

Callers normally configure only one value. The frontend and SDK derive the other
value with a fixed 30-second buffer:

```text
Only create_timeout is set:   schedule_timeout = create_timeout - 30
Only schedule_timeout is set: create_timeout = schedule_timeout + 30
Both are set:                 schedule_timeout <= create_timeout,
                              with a difference of at least 30 seconds
Neither is set:               create_timeout comes from
                              YR_SANDBOX_CREATE_TIMEOUT or defaults to 60,
                              then schedule_timeout is derived
```

This buffer reserves time after scheduling for rootfs/image preparation,
runtime startup, and Running-state confirmation. It is separate from any
additional SDK HTTP transport buffer used to receive the final response.

The SDK sends both resolved budgets in the create request:

```json
{
  "createTimeoutSeconds": 120,
  "scheduleTimeoutSeconds": 90
}
```

The frontend maps them to the overall librt create wait and scheduling wait:

```go
invokeOpts.Timeout = createTimeoutSeconds
invokeOpts.ScheduleTimeoutMs = scheduleTimeoutSeconds * 1000
```

`call_timeout` and `init_call_timeout` are not part of this alignment and retain
their existing meanings.

### 2. Deliver progress and the final create result over SSE

The SDK uses SSE create mode by default instead of waiting for a silent, long
HTTP JSON response.

The request remains on the create endpoint:

```http
POST /api/sandbox/v1/sandboxes
Accept: text/event-stream
```

Example request body:

```json
{
  "name": "sandbox-xxx",
  "image": "python3.12-slim",
  "createTimeoutSeconds": 120,
  "scheduleTimeoutSeconds": 90,
  "idleTimeoutSeconds": 300,
  "tunnel": {"enabled": true}
}
```

The frontend continuously flushes SSE events on the same connection:

```text
event: accepted
data: {"sandboxId":"default-sandbox-xxx","status":"creating"}

: heartbeat

: heartbeat

event: final
data: {"sandboxId":"default-sandbox-xxx","status":"running","tunnel":{...}}
```

An explicit failure is returned as the single final event:

```text
event: final
data: {"status":"failed","errorCode":3012,"message":"rootfs failed"}
```

A logical timeout is also returned as the single final event:

```text
event: final
data: {"status":"timeout","message":"create timed out"}
```

The frontend emits a heartbeat every two seconds to keep the connection active
across EIPs, load balancers, and ingress proxies. It closes the SSE connection
after writing the final event.

### 3. Do not introduce a shared operation store

This design does not add shared `/operations/{id}` state and does not promise to
recover a create result across frontend instances after a disconnect.

The trade-offs are:

- A create succeeds only when the SDK receives `final: running` on the current
  SSE connection within `createTimeoutSeconds`.
- If the SSE connection closes, the load balancer resets it, or the frontend pod
  restarts before the final event, the SDK treats the create as failed or
  indeterminate.
- When the `sandboxId` is known, the SDK may issue a best-effort DELETE. If
  cleanup fails, cluster-side `idleTimeoutSeconds` garbage collection remains
  the fallback.
- Avoiding shared operation state keeps this change bounded and reduces
  operational complexity.

SSE is therefore the create-result transport, not a recoverable operation
protocol.

### 4. Correct timeout-as-success handling

The frontend must not treat every `3002 + instanceID` result as success.

The only timeout case that may still become successful is:

```text
librt returns 3002 + instanceID, and the frontend confirms that the instance is Running
```

The frontend checks the shared instance view for the requested function and
resource specification for up to five seconds, polling every 200 milliseconds.
Only a confirmed Running state permits this final event:

```text
event: final
data: {"status":"running", ...}
```

Any other timeout case, including:

```text
3002 + instanceID + Running state not confirmed
```

must return a timeout or failed result instead of `200 + status=running`.

## External contract

### SDK contract for users

When `Sandbox(...)` returns successfully, the sandbox is Running. Commands,
files, shells, and tunnels can use it as a ready instance.

When `Sandbox(...)` raises an error:

```text
The SDK has not confirmed that the sandbox is usable.
```

Possible failures include:

- an explicit frontend/librt failure, such as rootfs preparation, image pulling,
  or runtime startup failure;
- failure to reach Running within `createTimeoutSeconds`;
- an SSE disconnect before the final event, which the SDK treats as a failed or
  indeterminate create;
- an HTTP, SSE protocol, or authentication error.

### Frontend contract for the SDK

Receiving an `instanceID` alone no longer means that creation succeeded. The
frontend sends a successful final event only after confirming Running. Otherwise
it sends an explicit failed or timeout final event. If the connection has already
closed, the frontend does not guarantee that the SDK can recover the final
operation result.

### Disconnect and orphan handling

If SSE disconnects before the final event, the SDK treats the create as
unsuccessful. If the backend instance later reaches Running, it is considered an
orphan and is reclaimed by the idle timeout. The SDK may attempt a best-effort
delete, but cleanup failure does not change the user-visible result: the original
`Sandbox(...)` call still fails.

### Explicitly unsupported behavior

This design does not guarantee:

- reconnecting an SSE stream to resume the same create operation;
- shared operation state across frontend replicas;
- conflict-free retries with a fixed sandbox name when an orphan was created;
- treating a sandbox as usable when the SDK did not receive `final: running`.

If future requirements include reconnect recovery, cross-frontend queries, or
idempotent retries that preserve the final failure reason, introduce a shared
operation store or reuse shared instance/create state in a separate design.

## Implementation sequence

1. **Eliminate false success:** do not report success for
   `3002 + instanceID` unless Running is confirmed.
2. **Align timeout budgets:** allow SDK/REST callers to provide either the create
   or schedule timeout, derive the other value, and set `invokeOpts.Timeout` and
   `invokeOpts.ScheduleTimeoutMs`.
3. **Add SSE create mode:** emit frontend heartbeat/final events and parse the
   final event in the SDK.
4. **Add best-effort cleanup:** when SSE disconnects and the `sandboxId` is known,
   attempt DELETE and fall back to idle-timeout garbage collection.
5. **Add regression coverage:** cover Running, explicit failure, timeout, SSE
   disconnect, invalid images, and reverse-tunnel create failures that must not be
   hidden by a later tunnel timeout.
