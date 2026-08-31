# Invoke Agent Instance

## Description

This API is used in the openYuanrong cluster to make **one synchronous call** against an already-created resident agent instance, driving the user handler inside the instance to run once and returning its return value. It pairs with [Create Agent Instance](./create_agent_instance.md): create returns an `instance_id`, and the caller uses that ID to call invoke to drive the instance.

One invoke corresponds to one execution of the user handler and returns that handler's return value. The agent model is single-instance, serial, synchronous, with no streaming return.

> **Difference between invoke and [Agent Instance Protocol Invocation Channels](./agent_invoke_channels.md)**: agent_invoke_channels (the SSH/WS/HTTP passthrough channels) bridges bytes verbatim to an **arbitrary server port** inside the sandbox, transparent to the upper-layer protocol; invoke is an HTTP API that synchronously drives the **user code entry** inside the instance by `instanceId` once and returns the user handler's return value. The two are orthogonal and can be used independently.

## Prerequisites

- The openYuanrong cluster is deployed and healthy; frontend is running (`yr start --master`, frontend included by default).
- An instance has been created via [Create Agent Instance](./create_agent_instance.md) and its `instance_id` obtained; the instance is `RUNNING`.
- The user code entry is already registered inside the instance:
  - **registered mode**: `handler`/`codePath` were passed when registering the function, and the create request `mounts` mounted the host code directory to `target == that codePath`.
  - **inline mode**: the create request `runtime_spec` carried `codePath`+`handler`, and `mounts` mounted the host code directory to `target == runtime_spec.codePath`.
- A missing `handler` makes invoke return an `empty user call code` execution error; a missing `codePath` or a code directory not in place makes the instance fail at startup load, and invoke returns a routing failure or timeout (see Error Codes and Troubleshooting).

## Constraints

- `instanceId` is required, the `instance_id` (UUID) returned at create. A non-existent, deleted, or just-restarted/migrated instance that misses the cache uniformly returns **404**.
- The request body is **arbitrary business JSON** and is fed to the user handler as the event. An empty body is treated as `{}`.
- **Synchronous single-value return**: one invoke corresponds to one execution of the user handler and returns that handler's return value; no streaming SSE.
- **create does not validate the presence of `codePath`/`handler`** (see [Create Agent Instance](./create_agent_instance.md)); whether both are complete is surfaced by the runtime at invoke time as an explicit execution error rather than a system exception.
- **Auth**: `/api/agent` goes through frontend's global `GlobalJwtAuthMiddleware`, consistent with [Create Agent Instance](./create_agent_instance.md) and other Function Service REST APIs. When `enable_func_token_auth` is off it is allowed by default (caller trusted); when on a valid JWT must be carried.

## URI

`POST /api/agent/:instanceId/invoke`

## Request Parameters

### Request Path Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| -------- | ---------- | ---------- | ----------- |
| instanceId | Yes | string | Instance ID (UUID returned at create). |

### Request Header Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| ----------- | ---------- | ---------- | ----------- |
| Content-Type | No | string | Message body type. `application/json` recommended. |
| tenantId | No | string | Tenant ID. Default `default`. |
| X-Trace-Id | No | string | Caller trace ID. If absent, frontend generates one and passes it through to the user handler. |
| traceparent | No | string | W3C traceparent, used for distributed tracing. |

### Request Body Parameters

The request body is **arbitrary business JSON** and is fed to the user handler as the event as a whole. There is no fixed schema; the fields are defined by the user handler.

## Response Parameters

| **Name** | **Type** | **Description** |
| -------- | -------- | -------- |
| code | int | Status code; `200` means success. On success the HTTP status code is `200`. |
| data | any | Return value of the user handler (returned on success). |
| message | string | Error message returned on failure. |

## Examples

### Prerequisite: create an instance with a code entry

Either registered or inline mode works, as long as create carries the full code entry and the code directory is mounted in place. Taking inline+supervisor as an example (`mounts[0].target` == `runtime_spec.codePath`):

```bash
curl -s -X POST http://{frontend}:8888/api/agent -H "Content-Type: application/json" -d '{
  "name": "agent-inline",
  "namespace": "dev",
  "runtime_spec": {
    "runtime": "python3.11",
    "sandbox_type": "supervisor",
    "codePath": "/opt/mycode/service",
    "handler": "demo.handler",
    "extendedHandler": {
      "initializer": "demo.init",
      "pre_stop": "demo.pre_stop"
    },
    "rootfs": {
      "imageurl": "yr-docker-runtime:v0",
      "user": "agentos",
      "ports": [
        "tcp:22"
      ]
    },
    "cpu": 600,
    "memory": 512
  },
  "mounts": [
    {
      "source": "/opt/mycode/service",
      "target": "/opt/mycode/service",
      "readonly": false
    }
  ]
}'
# {"code":200,"instance_id":"0b6c6322-6533-4901-8000-00000000bb0b"}
export INSTANCE_ID=0b6c6322-6533-4901-8000-00000000bb0b
```

### Drive the instance to execute

```bash
curl -s -X POST http://{frontend}:8888/api/agent/${INSTANCE_ID}/invoke \
  -H "Content-Type: application/json" \
  -d '{"event": "hello", "n": 42}'
```

Response (`data` is `demo.handler`'s return value for the event):

```json
{"code":200,"data":{"echo":"hello","doubled":84}}
```

> The examples use plaintext intranet calls with auth disabled; in production, prefer `https://` and enable `enable_func_token_auth`, carrying a valid JWT in the request.

### Error invocations

```bash
# invoke a non-existent instance → 404
curl -s -X POST http://{frontend}:8888/api/agent/not-exist/invoke -d '{}'
# {"code":404,"message":"instance not found: not-exist"}

# invoke after creating inline without codePath/handler → execution error
curl -s -X POST http://{frontend}:8888/api/agent/${INSTANCE_ID}/invoke -d '{"x":1}'
# {"code":500,"message":"invoke failed: code=... empty user call code ..."}
```

## Error Codes

| **HTTP status** | **Description** |
| -------- | -------- |
| 200 | OK. `data` is the user handler's return value. |
| 400 | Bad Request. `message` is of the form `failed to build invoke request: ...` (request body read failure, etc.). |
| 404 | Not Found. The instance does not exist / was deleted / just restarted or migrated causing a cache miss; `message` is of the form `instance not found: <id>`. |
| 500 | Internal Server Error. `message` is of the form `invoke failed: code=<n> err=<runtime error>` (in-instance execution error, including `empty user call code` for a missing handler, `faas inner error code <n>`, etc.); or `invoke failed: <err>` (underlying call failure / timeout). |

## Troubleshooting

- **404 `instance not found`**: the instance is not in the cache (never created / deleted / just restarted or migrated). First `GET /api/agent/${INSTANCE_ID}` to confirm the instance exists; if deleted, re-create.
- **500 `invoke failed: code=... empty user call code`**: no user handler is registered inside the instance. For registered, check that `handler` was non-empty when registering the function; for inline, check that `runtime_spec.handler` was passed at create.
- **500 instance routing failure / timeout**: the instance failed at the startup load phase (module not found, instance did not come up). Two root causes: (1) missing `codePath` — `runtime_spec.codePath` was not passed for inline; (2) `codePath` was passed but the directory was not in place — `mounts` is missing or `mounts[].target` does not align with `codePath`, so the runtime gets the path string but that path is empty inside the sandbox. Check that `mounts` contains a mount with `target == codePath` and that its `source` host directory exists and contains the module file.
- **500 with `invalid function`**: the instance and executor metadata are inconsistent (usually due to an abnormal instance or migration). Re-create the instance and retry.
