# Agent Instance Command Execution (exec)

## Description

This API executes commands inside an already-created Agent instance's own container. The command runs directly in the agent instance's own sandbox; no additional sandbox container is created.

Differences from other instance APIs:

- [Invoke Agent Instance](./invoke_agent_instance.md) (invoke): invokes the function logic hosted by the agent instance;
- Sandbox APIs: create a separate sub-sandbox to run commands.

exec reuses the instance's own container and can be combined with [Agent Instance File Operations](./agent_file_operations.md) (file upload/download, directory creation) for file management and environment inspection inside the instance.

## Constraints

- `instanceId` must be the `instance_id` (UUID) returned when the Agent instance was created. A non-existent or already-deleted instance returns 404.
- Authentication goes through frontend's global `GlobalJWTAuthMiddleware`, consistent with other function service REST APIs. When `enable_func_token_auth` is on, a valid JWT must be carried (see the auth section of [Agent Instance Protocol Invocation Channels](./agent_invoke_channels.md)).
- The request body must be valid JSON; `command` is a required field. Type errors in `working\_dir`, `env`, or `timeout` return 400.
- The request body and response body size cap is **512MB**; exceeding it returns 413.
- `timeout` must be greater than 0. If empty, the default timeout of 300 seconds applies. After the timeout, the command's process group (including child processes) is force-killed with SIGKILL and `returncode` returns -1.
- This API blocks synchronously until the command completes or times out. Do not run long-hanging commands.
- When the Executor's concurrent request limit is exceeded, 503 is returned; retry later.

## Interface Definition

URI: `POST /api/agent/{instanceId}/exec`

The request method is `POST` with Content-Type `application/json` (JSON request body).

### Request Path Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| -------- | -------- | -------- | ----------- |
| instanceId | Yes | string | Instance ID (the UUID returned at creation). |

## Request Parameters (Body, JSON)

| **Parameter** | **Required** | **Type** | **Description** |
| ----------- | -------- | -------------------------- | ------------------------------------------------------------------------- |
| command | Yes | string or `array<string>` | The command to execute. A string is executed through `/bin/sh -c`; an array is executed directly as argv. |
| working\_dir | No | string | Working directory for command execution. If empty, the instance process's current working directory is used. |
| env | No | `object<string, string>` | Environment variables for command execution. If empty, the instance process's environment is inherited. |
| timeout | No | number | Timeout in seconds; must be greater than 0. If empty, the default timeout of 300 seconds applies. After the timeout the command's process group is force-killed and returncode returns -1. |

## Response Parameters

| **Name** | **Type** | **Description** |
| ---------- | ------ | ------------------------------- |
| returncode | int | Command return code. 0 means success; -1 means timeout or execution error. |
| stdout | string | Standard output. |
| stderr | string | Standard error. Contains timeout information on timeout. |

> **Note**: HTTP 200 only indicates the command execution flow completed; whether the command itself succeeded is determined by `returncode` (0 means success, -1 means timeout or execution error).

## Request Examples

Execute a simple command (string form, executed via `/bin/sh -c`):

```bash
curl -X POST "http://{frontend}:8888/api/agent/{instanceId}/exec" \
  -H "Content-Type: application/json" \
  -H "X-Auth: {access_token}" \
  -d '{"command": "ls -la /tmp"}'
```

With working directory and environment variables:

```bash
curl -X POST "http://{frontend}:8888/api/agent/{instanceId}/exec" \
  -H "Content-Type: application/json" \
  -H "X-Auth: {access_token}" \
  -d '{"command": "echo $MY_VAR", "working_dir": "/home/agentos", "env": {"MY_VAR": "hello"}}'
```

`command` as an array (argv form):

```bash
curl -X POST "http://{frontend}:8888/api/agent/{instanceId}/exec" \
  -H "Content-Type: application/json" \
  -H "X-Auth: {access_token}" \
  -d '{"command": ["/bin/sh", "-c", "echo hello > /tmp/out.txt"]}'
```

## Response Examples

Command succeeded:

```json
{"returncode": 0, "stdout": "total 8\ndrwxr-xr-x 2 root root 4096 ...", "stderr": ""}
```

Command timed out (e.g. the caller set `"timeout": 5`):

```json
{"returncode": -1, "stdout": "", "stderr": "Command timed out after 5 seconds"}
```

## Error Codes

| **HTTP status** | **Description** |
| ----------- | ----------------------------------------------------------------------------- |
| 200 | Command execution completed. `returncode` may be non-zero; see `returncode`/`stdout`/`stderr` for details. |
| 400 | Bad request. `command` field missing, `working_dir`/`env`/`timeout` type errors, or the request body is not valid JSON. |
| 404 | Instance does not exist or has been deleted. |
| 413 | Request body or response body exceeds the 512MB limit. |
| 500 | Internal server error. |
| 503 | Executor overloaded (concurrent request limit exceeded). |

## Usage Notes

- Commands run inside the agent instance's own container and can access the instance filesystem. Combined with file upload/download and directory creation APIs, in-instance file management is possible (see [Agent Instance File Operations](./agent_file_operations.md)).
- A string `command` is equivalent to shell execution and supports pipes, redirection, and other shell syntax. Use the array form when precise argv control is needed or to avoid shell parsing ambiguity.
- Set a reasonable `timeout` for long-running commands; on timeout the process group (including child processes) is killed with SIGKILL and `stderr` contains timeout information.
- This API blocks synchronously until the command completes or times out. Do not run long-hanging commands (e.g. persistent foreground processes); such scenarios should be handled by the business logic hosted in the instance itself.
