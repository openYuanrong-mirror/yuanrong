# Agent 实例命令执行 (exec)

## 功能介绍

该 API 用于在已创建的 Agent 实例自身容器内执行命令。命令在 agent 实例所在沙箱中直接执行，不会创建额外的沙箱容器。

区别于其它实例接口：

- [调用 Agent 实例](./invoke_agent_instance.md)（invoke）：调用 agent 实例承载的函数逻辑；
- sandbox 接口：创建独立的子沙箱执行命令。

exec 直接复用实例自身容器，可与 [Agent 实例文件操作](./agent_file_operations.md)（上传/下载文件、创建目录）配合，完成实例内的文件管理与环境探测。

## 接口约束

- `instanceId` 必须为创建 Agent 实例时返回的 `instance_id`（UUID）。不存在或已删除的实例返回 404。
- 鉴权遵循 frontend 全局 `GlobalJWTAuthMiddleware`，与其它函数服务 REST API 一致。`enable_func_token_auth` 开时须携带有效 JWT（见 [Agent 实例协议调用通道](./agent_invoke_channels.md) 鉴权说明）。
- 请求体必须是合法 JSON，`command` 为必选字段；`working\_dir`、`env`、`timeout` 类型错误时返回 400。
- 请求体或响应体大小上限为 **512MB**，超过时返回 413。
- `timeout` 必须大于 0。为空时使用默认超时 300 秒；超时后命令进程组（含子进程）被 SIGKILL 强制终止，`returncode` 返回 -1。
- 该接口同步阻塞直至命令完成或超时，请勿执行长时间挂起的命令。
- Executor 并发请求超限时返回 503，可稍后重试。

## 接口定义

URI：`POST /api/agent/{instanceId}/exec`

请求方法为 `POST`，Content-Type 为 `application/json`（请求体为 JSON）。

### 请求 Path 参数

| **参数**     | **是否必选** | **参数类型** | **描述**                     |
| ---------- | -------- | -------- | -------------------------- |
| instanceId | 是        | string   | 实例 ID（创建 Agent 实例时返回的 UUID）。 |

## 请求参数（Body，JSON）

| **参数**       | **是否必选** | **参数类型**                   | **描述**                                                                    |
| ------------ | -------- | -------------------------- | ------------------------------------------------------------------------- |
| command      | 是        | string 或 `array<string>`   | 要执行的命令。字符串时通过 `/bin/sh -c` 执行；数组时直接作为 argv 执行。                              |
| working\_dir | 否        | string                     | 命令执行的工作目录。为空时使用实例进程当前工作目录。                                                  |
| env          | 否        | `object<string, string>`   | 命令执行的环境变量。为空时继承实例进程环境变量。                                                    |
| timeout      | 否        | number                     | 超时秒数，必须大于 0。为空时使用默认超时 300 秒。超时后命令进程组被强制终止，返回 returncode 为 -1。                |

## 响应参数

| **名称**     | **类型** | **描述**                          |
| ---------- | ------ | ------------------------------- |
| returncode | int    | 命令返回码。0 表示成功，-1 表示超时或执行错误。      |
| stdout     | string | 标准输出。                            |
| stderr     | string | 标准错误。超时时包含超时信息。                   |

> **注意**：HTTP 200 仅表示命令执行流程完成，命令本身是否成功以 `returncode` 为准（0 表示成功，-1 表示超时或执行错误）。

## 请求示例

执行简单命令（字符串形式，经 `/bin/sh -c` 执行）：

```bash
curl -X POST "http://{frontend}:8888/api/agent/{instanceId}/exec" \
  -H "Content-Type: application/json" \
  -H "X-Auth: {access_token}" \
  -d '{"command": "ls -la /tmp"}'
```

带工作目录和环境变量：

```bash
curl -X POST "http://{frontend}:8888/api/agent/{instanceId}/exec" \
  -H "Content-Type: application/json" \
  -H "X-Auth: {access_token}" \
  -d '{"command": "echo $MY_VAR", "working_dir": "/home/agentos", "env": {"MY_VAR": "hello"}}'
```

`command` 为数组（argv 形式）：

```bash
curl -X POST "http://{frontend}:8888/api/agent/{instanceId}/exec" \
  -H "Content-Type: application/json" \
  -H "X-Auth: {access_token}" \
  -d '{"command": ["/bin/sh", "-c", "echo hello > /tmp/out.txt"]}'
```

## 响应示例

命令执行成功：

```json
{"returncode": 0, "stdout": "total 8\ndrwxr-xr-x 2 root root 4096 ...", "stderr": ""}
```

命令超时（如调用方设置 `"timeout": 5`）：

```json
{"returncode": -1, "stdout": "", "stderr": "Command timed out after 5 seconds"}
```

## 错误码

| **HTTP 状态** | **描述**                                                                        |
| ----------- | ----------------------------------------------------------------------------- |
| 200         | 命令执行完成。`returncode` 可能非 0，以 `returncode`/`stdout`/`stderr` 为准。                  |
| 400         | 错误的请求。缺少 `command` 字段、`working_dir`/`env`/`timeout` 类型错误、请求体不是合法 JSON。          |
| 404         | 实例不存在或已删除。                                                                      |
| 413         | 请求体或响应体超过大小限制（512MB）。                                                            |
| 500         | 内部服务器错误。                                                                          |
| 503         | Executor 过载（并发请求超限）。                                                              |

## 使用说明

- 命令在 agent 实例自身容器内执行，可访问实例文件系统；与上传/下载文件、创建目录接口配合，可完成实例内文件管理（见 [Agent 实例文件操作](./agent_file_operations.md)）。
- `command` 为字符串时等价于 shell 执行，支持管道、重定向等 shell 语法；需要精确控制 argv、避免 shell 解析歧义时使用数组形式。
- 长时间运行的命令建议设置合理的 `timeout`；超时后进程组（含子进程）会被 SIGKILL 终止，`stderr` 中包含超时信息。
- 该接口同步阻塞直至命令完成或超时，请勿执行长时间挂起的命令（如常驻前台进程）；此类场景应通过实例承载的业务逻辑自行处理。
