# Agent 实例文件操作

## 功能介绍

该组 API 用于在已创建的 Agent 实例文件系统中进行文件上传、下载、列表和目录创建操作。所有操作通过 Frontend 已有的 TCP 隧道流式转发到 Agent Executor HTTP server，与 SSH、WebSocket 等通道复用同一鉴权连接。

## 接口约束

- `instanceId` 必须为创建 Agent 实例时返回的 `instance_id`（UUID）。不存在或已删除的实例返回 404。
- 鉴权遵循 frontend 全局 `GlobalJWTAuthMiddleware`，与其它函数服务 REST API 一致。`enable_func_token_auth` 开时须携带有效 JWT（见 [Agent 实例协议调用通道](./agent_invoke_channels.md) 鉴权说明）。
- 文件上传大小上限为 **512MB**（`maxFileUploadSize`）。Frontend 在读取 body 前先校验 `Content-Length`，超过 513MB（512MB + 1MB multipart 开销余量）直接返回 413 拒绝；`Content-Length` 介于 512MB\~513MB 之间的请求通过预校验，但若实际文件内容（去除 multipart 边界开销后）超过 512MB，则在流式读取时中止传输并返回 413。两种情况下，413 响应均在发送响应体之前返回，客户端可据此检测错误，减小文件后重试。
- 下载支持 HTTP `Range` 头进行断点续传。对空文件（0 字节）发起带 Range 的下载请求返回 416（符合 RFC 7233），不带 Range 则正常返回 200 + 空响应体。
- 上传使用 `multipart/form-data` 表单，`path` 字段必须在 `file` 字段之前。
- 上传若目标文件已存在则覆盖（通过临时文件原子替换）。
- 所有接口的 `path` 参数为实例内绝对路径。所有调用方须已通过 JWT 鉴权，视为可信用户。安全性由 Agent 实例自身的文件系统隔离（容器级或进程级沙箱）保证，不做额外的路径遍历校验。路径中包含 NUL 字节（`\x00`）时返回 400。
- `mode` 参数为 3\~4 位八进制字符串（正则 `^[0-7]{3,4}$`），如 `644`、`755`、`4755`。传入非法格式（如 `abc`、`999`、`7x5`）时返回 400。特殊位（SUID `4xxx`、SGID `2xxx`、sticky `1xxx`）允许设置，与标准 `chmod` 行为一致。调用方对在实例内设置的权限自行负责。

## 上传文件

### URI

`POST /api/agent/:instanceId/files/upload`

### 请求参数

#### 请求 Path 参数

| **参数**     | **是否必选** | **参数类型** | **描述**              |
| ---------- | -------- | -------- | ------------------- |
| instanceId | 是        | string   | 实例 ID（创建时返回的 UUID）。 |

#### 请求 Query 参数

| **参数** | **是否必选** | **参数类型** | **描述**                                                  |
| ------ | -------- | -------- | ------------------------------------------------------- |
| mode   | 否        | string   | 文件权限（3\~4 位八进制，如 `644`、`755`、`4755`）。为空则不设置。非法格式返回 400。 |

#### 请求 Body 参数（multipart/form-data）

| **名称** | **类型** | **是否必选** | **描述**                                       |
| ------ | ------ | -------- | -------------------------------------------- |
| path   | string | 是        | 上传目标路径（实例内绝对路径）。**必须在** **`file`** **字段之前。** |
| file   | binary | 是        | 文件内容。                                        |

### 响应参数

| **名称**  | **类型**  | **描述**          |
| ------- | ------- | --------------- |
| code    | int     | 状态码，`200` 表示成功。 |
| success | boolean | 是否上传成功。         |
| path    | string  | 实际写入路径。         |
| size    | int     | 实际写入字节数。        |

### 示例

```bash
curl -X POST "http://{frontend}:8888/api/agent/0b6c6322-6533-4901-8000-00000000bb0b/files/upload?mode=644" \
  -F "path=/home/agentos/upload.bin" \
  -F "file=@./local_file.bin"
# 开启鉴权时携带：-H "X-Auth: <jwt>"
```

响应：

```json
{"code":200,"success":true,"path":"/home/agentos/upload.bin","size":1048576}
```

### 错误码

| **HTTP 状态** | **描述**                                                                        |
| ----------- | ----------------------------------------------------------------------------- |
| 200         | 上传成功。                                                                         |
| 400         | 错误的请求。`path` 为空、`file` 字段缺失、`path` 字段未在 `file` 之前、`mode` 格式非法、multipart 解析失败。 |
| 404         | 实例不存在或已删除。                                                                    |
| 413         | 文件大小超过 512MB 限制。                                                              |
| 500         | 内部服务器错误。写入文件时发生 OS 级错误（如磁盘空间不足），或目标路径是已存在的目录。                                 |

## 下载文件

### URI

`GET /api/agent/:instanceId/files/download`

### 请求参数

#### 请求 Path 参数

| **参数**     | **是否必选** | **参数类型** | **描述**              |
| ---------- | -------- | -------- | ------------------- |
| instanceId | 是        | string   | 实例 ID（创建时返回的 UUID）。 |

#### 请求 Query 参数

| **参数** | **是否必选** | **参数类型** | **描述**           |
| ------ | -------- | -------- | ---------------- |
| path   | 是        | string   | 下载文件路径（实例内绝对路径）。 |

#### 请求 Header 参数

| **参数** | **是否必选** | **参数类型** | **描述**                                                            |
| ------ | -------- | -------- | ----------------------------------------------------------------- |
| Range  | 否        | string   | 标准 HTTP Range 头，用于断点续传。格式 `bytes=<start>-<end>`，如 `bytes=0-1023`。 |

### 响应参数

响应体为文件的二进制流。响应头包含：

| **名称**         | **类型** | **描述**                                             |
| -------------- | ------ | -------------------------------------------------- |
| Content-Type   | string | 始终为 `application/octet-stream`。                    |
| Content-Length | string | 响应体字节数。Range 请求时为分片长度（非文件总大小）。                     |
| Accept-Ranges  | string | 始终为 `bytes`，表示支持断点续传。                              |
| Content-Range  | string | 仅在 Range 请求成功时返回，格式 `bytes <start>-<end>/<total>`。 |

### 示例

```bash
# 完整下载
curl -o ./downloaded.bin "http://{frontend}:8888/api/agent/0b6c6322-6533-4901-8000-00000000bb0b/files/download?path=/home/agentos/data.bin"
# 开启鉴权时携带：-H "X-Auth: <jwt>"

# 断点续传（从第 1024 字节开始）
curl -o ./rest.bin -H "Range: bytes=1024-" "http://{frontend}:8888/api/agent/0b6c6322-6533-4901-8000-00000000bb0b/files/download?path=/home/agentos/data.bin"
```

### 错误码

| **HTTP 状态** | **描述**                                  |
| ----------- | --------------------------------------- |
| 200         | 下载成功（无 Range 头）。                        |
| 206         | 部分内容（Range 请求成功）。                       |
| 400         | `path` 为空。                              |
| 404         | 实例不存在或文件路径不存在。                          |
| 416         | Range 请求不可满足（如空文件带 Range、start 超过文件大小）。 |
| 500         | 内部服务器错误。读取文件时发生 OS 级错误，或路径是目录。          |

## 列举文件

### URI

`GET /api/agent/:instanceId/files/list`

### 请求参数

#### 请求 Path 参数

| **参数**     | **是否必选** | **参数类型** | **描述**              |
| ---------- | -------- | -------- | ------------------- |
| instanceId | 是        | string   | 实例 ID（创建时返回的 UUID）。 |

#### 请求 Query 参数

| **参数**     | **是否必选** | **参数类型** | **描述**                                                                                                                          |
| ---------- | -------- | -------- | ------------------------------------------------------------------------------------------------------------------------------- |
| path       | 是        | string   | 列举目标路径（实例内绝对路径）。文件或目录均可。当 `path` 指向文件时，`items` 包含该文件的单个元素。                                                                      |
| recursive  | 否        | string   | 是否递归列举子目录。取值 `true`/`false`，默认 `false`。                                                                                         |
| max\_depth | 否        | int      | 递归最大深度。仅在 `recursive=true` 时生效；当 `recursive=false` 时此参数被忽略。必须为非负整数。当为 `0`（默认）时使用系统上限 20。当传入值大于 20 时，会被静默截断为 20。传入负数或非整数时返回 400。 |

> **系统限制**：列举结果最多返回 **10000** 个条目（`DEFAULT_MAX_LIST_ENTRIES`），递归深度最大 **20** 层（`DEFAULT_MAX_LIST_DEPTH`）。超过任一限制时，结果被截断为该上限。递归和非递归列举均受 30 秒超时限制（`DEFAULT_LIST_TIMEOUT_SECONDS`），超时返回 504 错误。

### 响应参数

| **名称** | **类型** | **描述**          |
| ------ | ------ | --------------- |
| code   | int    | 状态码，`200` 表示成功。 |
| items  | array  | 文件/目录列表。每项见下表。  |

#### Item

| **名称**         | **类型**  | **描述**                |
| -------------- | ------- | --------------------- |
| name           | string  | 文件/目录名。               |
| path           | string  | 完整路径。                 |
| size           | int     | 字节数（目录为 0）。           |
| is\_directory  | boolean | 是否为目录。                |
| modified\_time | string  | 最后修改时间（ISO 8601 UTC）。 |
| type           | string  | `file` 或 `directory`。 |

### 示例

```bash
curl "http://{frontend}:8888/api/agent/0b6c6322-6533-4901-8000-00000000bb0b/files/list?path=/home/agentos&recursive=true&max_depth=2"
# 开启鉴权时携带：-H "X-Auth: <jwt>"
```

响应：

```json
{
  "code": 200,
  "items": [
    {"name": "data.bin", "path": "/home/agentos/data.bin", "size": 1048576, "is_directory": false, "modified_time": "2026-01-01T00:00:00+00:00", "type": "file"},
    {"name": "logs", "path": "/home/agentos/logs", "size": 0, "is_directory": true, "modified_time": "2026-01-01T00:00:00+00:00", "type": "directory"}
  ]
}
```

### 错误码

| **HTTP 状态** | **描述**                         |
| ----------- | ------------------------------ |
| 200         | 列举成功。                          |
| 400         | `path` 为空、`max_depth` 为负数或非整数。 |
| 404         | 实例不存在或路径不存在。                   |
| 504         | 列举超时（默认 30 秒）。                 |

## 创建目录

### URI

`POST /api/agent/:instanceId/files/mkdir`

### 请求参数

#### 请求 Path 参数

| **参数**     | **是否必选** | **参数类型** | **描述**              |
| ---------- | -------- | -------- | ------------------- |
| instanceId | 是        | string   | 实例 ID（创建时返回的 UUID）。 |

#### 请求 Query 参数

| **参数**    | **是否必选** | **参数类型** | **描述**                                            |
| --------- | -------- | -------- | ------------------------------------------------- |
| path      | 是        | string   | 创建目录路径（实例内绝对路径）。                                  |
| mode      | 否        | string   | 目录权限（3\~4 位八进制，如 `755`、`4755`）。为空则不设置。非法格式返回 400。 |
| recursive | 否        | string   | 是否递归创建父目录。取值 `true`/`false`，默认 `false`。           |

### 响应参数

| **名称**  | **类型**  | **描述**                                                                                 |
| ------- | ------- | -------------------------------------------------------------------------------------- |
| code    | int     | 状态码，`200` 表示成功。                                                                        |
| success | boolean | 是否创建成功。                                                                                |
| path    | string  | 实际创建路径。                                                                                |
| created | boolean | 目标目录本身是否为本次新建（`false` 表示已存在）。当 `recursive=true` 且父目录也被新建时，`created` 仅反映最终目标目录，不包括中间目录。 |

### 示例

```bash
curl -X POST "http://{frontend}:8888/api/agent/0b6c6322-6533-4901-8000-00000000bb0b/files/mkdir?path=/home/agentos/subdir&mode=755&recursive=true"
# 开启鉴权时携带：-H "X-Auth: <jwt>"
```

响应：

```json
{"code":200,"success":true,"path":"/home/agentos/subdir","created":true}
```

### 错误码

| **HTTP 状态** | **描述**                                              |
| ----------- | --------------------------------------------------- |
| 200         | 创建成功。                                               |
| 400         | `path` 为空、`mode` 格式非法、父目录不存在（未指定 `recursive=true`）。 |
| 404         | 实例不存在或已删除。                                          |
| 500         | 内部服务器错误。创建目录时发生 OS 级错误。                             |
