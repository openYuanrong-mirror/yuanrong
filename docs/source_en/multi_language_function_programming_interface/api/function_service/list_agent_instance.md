# List Agent Instances

## Description

This API is used to query the brief view of all agent instances currently in the openYuanrong cluster. It returns the identity and runtime/container addresses of every RUNNING instance in the cache, for global inspection and multi-instance navigation.

Data comes from frontend's local instance cache (execendpoint watcher) and **only reflects RUNNING instances currently in the cache**. The list is sorted by `instance_id`. System-internal drivers (driver-frontend/driver-scheduler, etc., which have no `sandbox_type`) are filtered out and not counted as user agent instances. When there are no instances, an empty array is returned rather than 404.

## Constraints

- No request parameters: the list returns every user agent instance in the cache, not filtered by `tenantId` (`tenantId` is only validated by the auth middleware and does not participate in instance selection).
- The list is a **brief view** (identity + addresses) and does not include create-time config; for single-instance detail call [Get Single Agent Instance](./get_agent_instance.md).
- Authentication goes through frontend's global `GlobalJwtAuthMiddleware`, consistent with other function service REST APIs. When `enable_func_token_auth` is on, a valid JWT must be carried (see the auth section of [Agent Instance Protocol Invocation Channels](./agent_invoke_channels.md)).
- Response fields are governed by `omitempty`: `sandbox_ip` is omitted when the instance has no assigned internal IP. Clients should tolerate field presence rather than assuming all fields are always present.

## URI

`GET /api/agent`

## Request Parameters

### Request Header Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| ----------- | ---------- | ---------- | ----------- |
| tenantId | No | string | Tenant ID. Only validated by the auth middleware; does not participate in instance filtering, defaults to `default`. |

No request Body / Path parameters.

## Response Parameters

The response body's `code` field `200` means success; the brief instance info is in the `instances` array. When there are no instances, `instances` is an empty array `[]`.

| **Name** | **Type** | **Description** |
| -------- | -------- | -------- |
| code | int | Status code; `200` means success. |
| instances | array | Brief instance list, sorted by `instance_id`. |

### instances element

| **Name** | **Type** | **Description** |
| -------- | -------- | -------- |
| instance_id | String | Instance ID (UUID). |
| node_ip | String | Host node IP (extracted from the owner proxy gRPC address). |
| sandbox_ip | String | Container internal IP (docker inspect or supervisor create response). Omitted when the instance has no assigned internal IP. |
| sandbox_type | String | Executor kind; `docker` / `supervisor`, from createOptions["sandbox_type"]. |

## Examples

```bash
curl http://{frontend}:8888/api/agent
# When auth is on, carry: -H "X-Auth: <jwt>"
```

> The example shows an in-cluster plaintext call with auth off; for production use `https://` and enable `enable_func_token_auth`, carrying a valid JWT.

Response (one docker + one supervisor):

```json
{
  "code": 200,
  "instances": [
    {
      "instance_id": "0b6c6322-6533-4901-8000-00000000bb0b",
      "node_ip": "10.0.0.5",
      "sandbox_ip": "172.17.0.5",
      "sandbox_type": "docker"
    },
    {
      "instance_id": "1a2b3c4d-5e6f-4789-8000-00000000bb0c",
      "node_ip": "10.0.0.6",
      "sandbox_ip": "10.0.0.66",
      "sandbox_type": "supervisor"
    }
  ]
}
```

When there are no instances:

```json
{"code":200,"instances":[]}
```

## Error Codes

| **HTTP status** | **Description** |
| -------- | -------- |
| 200 | OK. Returns the brief instance list (an empty `instances` array when there are none). |
| 401 | Unauthorized. When `enable_func_token_auth` is on, no JWT or an invalid JWT — returned by the global `GlobalJwtAuthMiddleware` before reaching the handler. |
| 403 | Forbidden. The JWT is valid but the caller lacks permission. |
