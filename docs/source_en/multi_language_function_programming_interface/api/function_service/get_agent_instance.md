# Get Single Agent Instance

## Description

This API is used to query the detailed status of a single agent instance in the openYuanrong cluster. It reaches the instance directly by `instanceId` and returns its identity, runtime address, container address, and the configuration at create time (rootfs/ports/env vars/resources/start time), for ops triage and troubleshooting.

Data comes from frontend's local instance cache (execendpoint watcher) and **only reflects RUNNING instances currently in the cache**. An instance that is deleted or has not yet reached the RUNNING cache returns 404. The query interface, like create/delete, makes no distinction between the inline / registered creation modes.

## Constraints

- `instanceId` must be the `instance_id` (UUID) returned when the agent instance was created. `GET /api/agent/` (empty trailing segment) routes to [List Agent Instances](./list_agent_instance.md) rather than this interface, so `instanceId` is never empty here.
- A non-existent, already-deleted, or not-yet-RUNNING `instanceId` returns 404 — this is intentional: the query interface only describes instances that currently exist and does not synthesize a view of absent ones.
- Authentication goes through frontend's global `GlobalJwtAuthMiddleware`, consistent with other function service REST APIs. When `enable_func_token_auth` is on, a valid JWT must be carried (see the auth section of [Agent Instance Protocol Invocation Channels](./agent_invoke_channels.md)).
- Response fields are governed by `omitempty`: when ports/env vars/rootfs are unconfigured the corresponding fields are omitted. Clients should tolerate field presence rather than assuming all fields are always present.

## URI

`GET /api/agent/:instanceId`

## Request Parameters

### Request Path Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| -------- | ---------- | ---------- | ----------- |
| instanceId | Yes | string | Instance ID (the UUID returned at creation). |

### Request Header Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| ----------- | ---------- | ---------- | ----------- |
| tenantId | No | string | Tenant ID. The query reaches the instance globally by `instanceId`; `tenantId` does not participate in instance filtering and defaults to `default`. |

## Response Parameters

The response body's `code` field `200` means success; the detailed instance info is in the `instance` object.

| **Name** | **Type** | **Description** |
| -------- | -------- | -------- |
| code | int | Status code; `200` means success. The HTTP status code on success is `200`. |
| instance | Object | Instance detail. Absent on failure. |
| message | String | Error message on failure. |

### instance object

| **Name** | **Type** | **Description** |
| -------- | -------- | -------- |
| instance_id | String | Instance ID (UUID). |
| node_ip | String | Host node IP (extracted from the owner proxy gRPC address). |
| sandbox_ip | String | Container internal IP (docker inspect or supervisor create response). Omitted when the instance has no assigned internal IP. |
| sandbox_type | String | Executor kind; `docker` / `supervisor`, from createOptions["sandbox_type"]. |
| sandbox_id | String | Container/sandbox ID (docker containerID or supervisor/runsc sandboxID). |
| rootfs | Object | rootfs detail. See rootfs object. Omitted when unconfigured. |
| ports | array | Port forwarding labels, format `<proto>:<port>` (e.g. `tcp:22`), from createOptions["network"]. Omitted when unconfigured. |
| env_vars | map | Dynamic env vars injected into the container, from createOptions["DELEGATE_ENV_VAR"]. Omitted when unconfigured. |
| resources | map | Resource usage (scalar values). `CPU` is in `1/1000` core units; `storage` is stored internally in bytes and converted to MiB for the public API (`bytes ÷ (1024×1024)`). |
| start_time | String | Instance start time (RFC3339, from the service side). Falls back to the watcher's local first-observed-RUNNING timestamp when the service-side value is missing. |

#### rootfs object

| **Name** | **Type** | **Description** |
| -------- | -------- | -------- |
| type | String | rootfs type; `image` for docker. |
| imageurl | String | docker image reference (e.g. `yr-docker-runtime:v0`). |
| user | String | Container run-as user, from createOptions["host_user"]. |
| workspace | String | Host workspace absolute path (the `workspace` create parameter), from createOptions["workspace"], distinguished from the workspace mount in the rootfs JSON. |
| mounts | array | Extra bind mount list. See mount object. |

#### mount object

| **Name** | **Type** | **Description** |
| -------- | -------- | -------- |
| source | String | Host absolute path. |
| target | String | In-container path. |
| readonly | boolean | Read-only flag. `false` is also printed explicitly. |

## Examples

```bash
curl http://{frontend}:8888/api/agent/0b6c6322-6533-4901-8000-00000000bb0b
# When auth is on, carry: -H "X-Auth: <jwt>"
```

> The example shows an in-cluster plaintext call with auth off; for production use `https://` and enable `enable_func_token_auth`, carrying a valid JWT.

Response (docker instance, full fields):

```json
{
  "code": 200,
  "instance": {
    "instance_id": "0b6c6322-6533-4901-8000-00000000bb0b",
    "node_ip": "10.0.0.5",
    "sandbox_ip": "172.17.0.5",
    "sandbox_type": "docker",
    "sandbox_id": "4fb6aa1c",
    "rootfs": {
      "type": "image",
      "imageurl": "yr-docker-runtime:v0",
      "user": "agentos",
      "workspace": "/home/snuser/workspaceA",
      "mounts": [{"source": "/data", "target": "/data", "readonly": false}]
    },
    "ports": ["tcp:22"],
    "env_vars": {"FOO": "bar"},
    "resources": {"CPU": 600, "storage": 200},
    "start_time": "2026-07-30T03:00:00Z"
  }
}
```

Supervisor instance (no rootfs/ports):

```json
{
  "code": 200,
  "instance": {
    "instance_id": "1a2b3c4d-5e6f-4789-8000-00000000bb0c",
    "node_ip": "10.0.0.6",
    "sandbox_ip": "10.0.0.66",
    "sandbox_type": "supervisor",
    "resources": {},
    "start_time": "2026-07-30T03:01:00Z"
  }
}
```

## Error Codes

| **HTTP status** | **Description** |
| -------- | -------- |
| 200 | OK. Returns the instance detail. |
| 401 | Unauthorized. When `enable_func_token_auth` is on, no JWT or an invalid JWT — returned by the global `GlobalJwtAuthMiddleware` before reaching the handler. |
| 403 | Forbidden. The JWT is valid but the caller lacks permission. |
| 404 | Not Found. `instanceId` does not exist, has been deleted, or has not yet reached the RUNNING cache; `message` is `instance not found or not running`. |
