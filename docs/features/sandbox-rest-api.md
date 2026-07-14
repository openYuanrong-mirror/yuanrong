# Sandbox RESTful API 参考

> openYuanrong sandbox 对外 HTTP/WebSocket 接口与 SDK 用法的单一参考。
> 运行时内部架构见 [`../rust-sandbox-runtime/README.md`](../rust-sandbox-runtime/README.md)。
>
> 状态：已按当前 frontend、sandboxRouter、rrt-runtime 与 Python SDK 实现更新。

---

## 1. 当前接口面

Sandbox 对外有三组 URL 面：

| 面 | 入口 | 主要路径 | 用途 |
|----|------|----------|------|
| Frontend control API | `YR_SERVER_ADDRESS` | `/api/sandbox/v1/sandboxes...` | create/delete/invoke 控制面 |
| Frontend direct alias | `YR_SERVER_ADDRESS` | `/direct/{safeID}/...` | 低延迟 RRT HTTP 数据面，隐藏 RRT 内部端口 |
| Sandbox gateway/router | `YR_GATEWAY_ADDRESS`，缺省回退 `YR_SERVER_ADDRESS` | `/tunnel/{safeID}`、`/{safeID}/{port}` | reverse tunnel 与用户端口转发 |

两条 action 数据面执行同一套 `{action, args}` 词表：

```text
SDK invoke ──优先──► POST /direct/{safeID}/invoke ─► frontend ─► sandboxRouter ─► rrt /invoke
          └─回退──► POST /api/sandbox/v1/sandboxes/{sandboxID}/invoke ─► frontend ─► libRt RuntimeRPC ─► rrt sandbox_invoke
```

- direct 可用时优先使用；`404` / `5xx` / 连接错误会让 SDK 对当前 client 粘性回退到 frontend invoke。
- direct URL 不暴露 `50090`；旧显式端口形式 `/direct/{safeID}/{rrtPort}/...` 只是 frontend 兼容入口，新 SDK 不应生成。
- binary 文件/目录传输走 `/direct/{safeID}/upload|download`，避免 JSON/base64 包装。

---

## 2. 鉴权、trace 与响应 envelope

### 2.1 JWT 与 token 传递

| 路径 | frontend JWT | 转发给 sandboxRouter/RRT | 说明 |
|------|--------------|---------------------------|------|
| `/api/sandbox/v1/...` | 需要（除非 frontend 全局关闭鉴权） | 不适用 | `X-Auth: <jwt>`，非 `Authorization: Bearer` |
| `/direct/{safeID}/...` | 需要 | frontend 删除 `X-Auth` / `token` / `tenant_id`，加 `X-Internal-Src: 1` | RRT 不接收平台 JWT |
| `/tunnel/{safeID}` | frontend 明确跳过 JWT | 删除平台凭据 | tunnel 由 create 时的授权动作建立，默认 `ws://` 不带 token |
| `/{safeID}/{port}` 用户端口 | sandboxRouter 不要求平台 JWT | 删除平台凭据 | 用户服务自行做业务鉴权 |
| 直接访问 `/{safeID}/{rrtPort}` | sandboxRouter 要 JWT | RRT 端口可保留 token | 仅作为低层兼容/调试路径，不是 SDK 主路径 |

frontend JWT 中间件会把 JWT `sub` 写入租户 header/query；`/direct` 转发前会删除这些平台路由参数，避免泄漏到 RRT。

### 2.2 Trace

- frontend sandbox API 会初始化/透传 `X-Trace-ID`。
- `/direct` 由 `sandboxTraceHandler` 包装，响应头也返回 `X-Trace-ID`。
- `/direct` invoke 可携带 `X-YR-Request-ID` 或 body `requestId`；RRT 对相同 requestId 的完成结果做 TTL 去重/replay。
- 如果请求携带 `traceparent`，frontend invoke 会放入 runtime `CustomExtensions["traceparent"]`。
- rrt HTTP 会读取 `X-Trace-ID` 并写入访问日志。

### 2.3 frontend response envelope

`/api/sandbox/v1/...` 使用 frontend 统一响应 envelope：

```json
{
  "code": 200,
  "message": "",
  "data": "<base64(json)>"
}
```

说明：

- `data` 是 Go `[]byte`，JSON 编码后表现为 base64 字符串。
- SDK 会 base64 解码后再 JSON parse。
- `/direct/...` 不使用该 envelope：`/invoke` 和 `/upload` 返回原始 JSON，`/download` 返回二进制流。

---

## 3. Frontend Sandbox v1 API

Base：`{scheme}://{YR_SERVER_ADDRESS}/api/sandbox/v1/sandboxes`，`scheme` 由 `YR_TLS` 决定（默认 HTTPS）。

| Method | Path | 说明 |
|--------|------|------|
| `POST` | `/api/sandbox/v1/sandboxes` | 创建 sandbox |
| `DELETE` | `/api/sandbox/v1/sandboxes/{sandboxID}` | 销毁 sandbox |
| `POST` | `/api/sandbox/v1/sandboxes/{sandboxID}/invoke` | frontend RuntimeRPC action 通道 |

`POST /api/sandbox/v1/sandboxes` returns an SSE stream when the request includes
`Accept: text/event-stream`.

Successful request example (each request has exactly one `final` event):

```text
event: accepted
data: {"status":"creating"}

event: final
data: {"sandboxId":"default/demo","status":"running"}
```

Timeout example:

```text
event: accepted
data: {"status":"creating"}

event: final
data: {"status":"timeout","errorCode":3002,"message":"create timed out"}
```

### 3.1 CreateV1Request

```json
{
  "name": "demo",
  "namespace": "default",
  "tenant": "default",
  "runtime": "rrt",
  "image": "python:3.12-slim",
  "rootfs": {"runtime": "runsc", "type": "image", "imageurl": "python:3.12-slim", "readonly": false},
  "ports": ["8080", "https:8443"],
  "idleTimeoutSeconds": 300,
  "createTimeoutSeconds": 120,
  "scheduleTimeoutSeconds": 90,
  "cpu": 1000,
  "memory": 2048,
  "cpu_limit": 0,
  "mem_limit": 0,
  "env": {"KEY": "value"},
  "mounts": [],
  "extra_config": {},
  "tunnel": {"enabled": true}
}
```

字段规则：

| 字段 | 说明 |
|------|------|
| `name` | 可选；为空时 frontend 生成 `sandbox-<unixNano>` |
| `namespace` | 可选；默认 `default` |
| `tenant` | 可选；也可由 JWT tenant header/query 覆盖 |
| `runtime` | 可选；默认 `rrt`；支持 `rrt`/`rrt-runtime`/`rust`、`python3.10`/`py310`、`python3.9`/`py39` |
| `image` / `rootfs` | `rootfs` 支持 `runtime,type,image,imageurl,path,readonly`；仅给 `image` 时 frontend 自动补 `rootfs.type=image`、`rootfs.runtime=runsc` |
| `ports` | 用户端口声明，格式为 `PORT`、`http:PORT` 或 `https:PORT`；frontend 会自动追加 RRT/tunnel 内部端口 |
| `cpu` / `memory` | 资源请求；未设置时 frontend 默认 `1000` / `2048` |
| `cpu_limit` / `mem_limit` | cgroup 上限；`0` 由底层按默认处理 |
| `createTimeoutSeconds` | Optional total create budget in seconds, from request start through Running confirmation. When omitted, it is derived as `scheduleTimeoutSeconds + 30`, or read from `YR_SANDBOX_CREATE_TIMEOUT`, with a default of 60. |
| `scheduleTimeoutSeconds` | Optional resource-scheduling budget in seconds. When omitted, it is derived as `createTimeoutSeconds - 30`. When both values are provided, `scheduleTimeoutSeconds <= createTimeoutSeconds` and their difference must be at least 30 seconds. |
| `env` | 用户环境变量；frontend 同时会注入 `RRT_HTTP_PORT` 以及 tunnel 相关 env |
| `mounts` / `extra_config` | 透传给 sandboxd/runtime launcher |
| `tunnel.enabled` | 请求 frontend 准备 reverse tunnel；SDK 使用 `upstream=` 时自动设置 |

响应（envelope 解码后的 `data`）：

```json
{
  "sandboxId": "default/xxx",
  "instanceId": "default/xxx",
  "status": "running",
  "tunnel": {
    "url": "/tunnel/<safeID>",
    "path": "/tunnel/<safeID>",
    "wsPath": "/tunnel/<safeID>",
    "proxyUrl": "http://127.0.0.1:8766",
    "proxyPort": 8766
  }
}
```

`tunnel` 仅在请求 `tunnel.enabled=true` 时返回。`proxyUrl` 是沙箱内代码访问 tunnel Port-B 的地址，不是外部 WebSocket 地址。

### 3.2 InvokeV1Request

请求：

```json
{"action": "process.exec", "args": {"cmd": "echo hi", "cwd": "/tmp"}}
```

- `action` 必填；为空返回 `400`。
- `args` 为空时按 `{}` 处理。
- frontend 通过 `sandbox_invoke` 投递给 RRT，返回 action 结果；若结果 JSON 包含非空 `error`，frontend envelope 的 `message` 会携带该错误。

## 4. Frontend direct alias 与 RRT HTTP API

SDK 主路径通过 frontend `/direct` alias 访问 RRT HTTP server。frontend 将 alias 转为 sandboxRouter 内部路径 `/{safeID}/{rrtPort}/...`。

| Method | Frontend alias | 转到 RRT | 说明 |
|--------|----------------|----------|------|
| `POST` | `/direct/{safeID}/invoke` | `POST /invoke` | `{action,args}` JSON，返回原始 action JSON |
| `GET` | `/direct/{safeID}/healthz` | `GET /healthz` | 健康检查 |
| `POST` | `/direct/{safeID}/upload?path=<abs>&type=file|tar` | `POST /upload?...` | 原始 bytes 或 tar stream 上传 |
| `GET` | `/direct/{safeID}/upload/status?path=<abs>&uploadId=<id>` | `GET /upload/status?...` | 查询 resumable file upload 已写 offset |
| `POST` | `/direct/{safeID}/upload/commit?path=<abs>&uploadId=<id>&totalSize=<n>` | `POST /upload/commit?...` | 校验大小并将 part 文件原子 rename 到目标路径 |
| `GET` | `/direct/{safeID}/download?path=<abs>&type=file|tar` | `GET /download?...` | 原始 bytes 或 tar stream 下载 |

上传协议：

- `type=file` 且不带 `uploadId`：body 直接写入目标文件；返回 JSON：`{error:null,name,path,type:"file",size,bytes_written}`。
- `type=file` 且带 `uploadId` / `offset`：body 追加写入 `.<name>.yr-upload.<uploadId>.part`；RRT 要求 offset 等于当前 part 大小，返回新的 `offset`。
- `GET /upload/status` 返回 `{error:null,path,uploadId,offset,exists}`，SDK 用它在连接失败后继续上传。
- `POST /upload/commit` 校验 `totalSize` 后将 part 文件 rename 到目标文件，返回最终 file entry。
- `type=tar`：body 是 tar stream，RRT 在目标目录解包；返回 JSON：`{error:null,name,path,type:"dir",size,bytes_written}`。目录 tar stream 暂不支持断点续传，manifest copy 作为后续 TODO。
- 支持 `Content-Length` 与 `Transfer-Encoding: chunked`。
- `Content-Type` 建议：file 用 `application/octet-stream`，tar 用 `application/x-tar`。

下载协议：

- `type=file`：返回 `application/octet-stream`，带 `Content-Length`；支持 `Range: bytes=<offset>-`，返回 `206` 和 `Content-Range`。
- SDK 下载到本地 `<target>.part`，失败后按 part 大小继续 range 下载，成功后 `os.replace()` 到目标文件。
- `type=tar`：返回 `application/x-tar`，通常不带 `Content-Length`；目录 tar 下载暂不支持断点续传。

RRT HTTP server 自身状态码：

| 状态码 | 说明 |
|--------|------|
| `200` | 成功 |
| `206` | Range download partial content |
| `400` | bad json、缺少 path、unsupported action/type 等 |
| `401` | RRT 静态 token 校验失败（仅设置 `RRT_HTTP_TOKEN` 时） |
| `404` | path 不存在、upload part 不存在或 route 不存在 |
| `409` | resumable upload offset/size mismatch |
| `431` | HTTP headers 过大 |
| `500` | direct invoke dispatch panic/join failure |

经 sandboxRouter 额外可能返回：`403`（租户不匹配）、`502`（后端未监听）、`503`（路由解析不可用）、`504`（上游超时）。

---

## 5. sandboxRouter 路由契约

router 入站路径：`/{safeID}/{port}[/rest]`。

| 入站 | 解析 | 转发 |
|------|------|------|
| `/inst-a/50090/invoke` | `safeID=inst-a`, `port=50090`, rest=`/invoke` | RRT `/invoke` |
| `/inst-a/8080/api/foo` | `safeID=inst-a`, `port=8080`, rest=`/api/foo` | 用户服务 `/api/foo` |

路由来源：

- `safeID` 由 `route.SanitizeID(instanceID)` 生成：`@` → `-at-`，`/._` → `-`。
- `port` 必须是已声明 containerPort。
- route resolver 从 `InstanceInfo.Extensions["portForward"]` 读取 `protocol:hostPort:containerPort`，用 `proxyGrpcAddress` 提取节点 IP。
- `protocol=https` 时 router 使用 HTTPS backend transport；其他协议按 HTTP 处理。WebSocket upgrade 复用 HTTP 反代。

鉴权策略（当前代码）：

- 只有 RRT control port（默认 50090）是 router control port。
- tunnel port（默认 8765）和用户端口都是公开路由，router 层不要求平台 JWT。
- frontend `/direct` 过来的请求带 `X-Internal-Src: 1` 且来自 loopback，router 跳过 RRT control port 二次鉴权并剥离平台凭据。
- 直接访问 router 的 RRT 端口仍需要 JWT，并会按 target tenant 做授权。

---

## 6. Action 词表

公开 action 通过 `normalize_sandbox_action` 归一。推荐 SDK/用户使用公开名：

| 类别 | 推荐 action | 别名 |
|------|-------------|------|
| 进程 | `process.exec` | `process.run`, `cmd.run`, `exec`, `cmd_run` |
| 进程 | `process.start` | `cmd.start`, `cmd_start` |
| 进程 | `process.poll` | `cmd.poll`, `cmd_poll` |
| 进程 | `process.wait` | `cmd.wait`, `cmd_wait` |
| 进程 | `process.kill` | `cmd.kill`, `cmd_kill` |
| 进程 | `process.list` | `cmd.list`, `cmd_list` |
| 进程 | `process.send_stdin` | `process.stdin`, `cmd.send_stdin`, `cmd_send_stdin` |
| 文件 | `file.read` | `fs.read`, `fs_read` |
| 文件 | `file.write` | `fs.write`, `fs_write` |
| 文件 | `file.write_chunk` | `file.upload.chunk`, `fs.write_chunk`, `fs_write_chunk` |
| 文件 | `file.read_chunk` | `file.download.chunk`, `fs.read_chunk`, `fs_read_chunk` |
| 文件 | `file.list` | `fs.list`, `fs_list` |
| 文件 | `file.exists` | `fs.exists`, `fs_exists` |
| 文件 | `file.remove` | `fs.remove`, `fs_remove` |
| 文件 | `file.rename` | `fs.rename`, `fs_rename` |
| 文件 | `file.mkdir` | `file.make_dir`, `fs.mkdir`, `fs.make_dir`, `fs_make_dir` |
| 文件 | `file.stat` | `file.info`, `fs.stat`, `fs.get_info`, `fs_get_info` |
| shell | `shell.create` | `shell.init`, `bash_init` |
| shell | `shell.run` | `shell.submit`, `bash_submit` |
| shell | `shell.poll` | `bash_poll` |
| shell | `shell.delete` | `shell.destroy`, `shell.close`, `bash_destroy` |

---

## 7. 主要 action 参数与返回

### 7.1 进程

| action | args | 返回 |
|--------|------|------|
| `process.exec` | `cmd`/`command`, 可选 `cwd`, `envs`/`env` | `{stdout, stderr, exit_code}` |
| `process.start` | `cmd`, 可选 `cwd`, `envs`, `want_stdin` | `{pid, error?}` |
| `process.poll` | `pid` | `{status, stdout, stderr, exit_code}` |
| `process.wait` | `pid`, 可选 `timeout` | `{stdout, stderr, exit_code}` |
| `process.kill` | `pid` | `{killed, error?}` |
| `process.list` | `{}` | `{processes: [...]}` |
| `process.send_stdin` | `pid`, `data`, `eof` | `{error?}` |

### 7.2 文件

| action | args | 返回 |
|--------|------|------|
| `file.read` | `path`, `binary` | 文本或二进制 hex 数据 |
| `file.write` | `path`, `data`, `binary` | `EntryInfo` |
| `file.list` | `path` | `EntryInfo[]` |
| `file.exists` | `path` | `{exists}` |
| `file.remove` | `path` | `{error?}` |
| `file.rename` | `old_path`, `new_path` | `EntryInfo` |
| `file.mkdir` | `path` | `{error?}` |
| `file.stat` | `path` | `EntryInfo` |
| `file.write_chunk` | `path`, `offset`, `data` | 分块写入进度 |
| `file.read_chunk` | `path`, `offset`, `size` | 分块读取数据 |

`EntryInfo` 主要字段：`name`, `path`, `type`, `size`, `permissions`, `modified_time`。

### 7.3 shell

| action | args | 返回 |
|--------|------|------|
| `shell.create` | `session_id`, `shell` | 会话信息或 `{error}` |
| `shell.run` | `session_id`, `command` | 提交结果 |
| `shell.poll` | `session_id` | 增量输出/状态 |
| `shell.delete` | `session_id` | `{error?}` |

---

## 8. Reverse tunnel 协议

创建 sandbox 时传 `"tunnel":{"enabled":true}`，frontend 会：

- 注入 `RRT_TUNNEL_WS_PORT`（默认 8765）和 `RRT_TUNNEL_HTTP_PORT`（默认 8766）。
- 将这两个端口加入 sandbox network ports。
- 在 create 响应中返回 `/tunnel/{safeID}` 和沙箱内 `proxyUrl`。

链路：

```text
本地服务 127.0.0.1:8000
      ▲
      │ TunnelClient 通过 ws(s)://<gateway>/tunnel/{safeID} 连入
      ▼
rrt tunnel WS Port-A 8765 ── RRT Port-B 127.0.0.1:8766 ── 沙箱内代码访问 http://127.0.0.1:8766/path
```

线协议：WebSocket TEXT JSON，`body` / `data` 字段使用 base64。

```json
{"type":"http_req","id":"uuid","method":"GET","path":"/health","headers":{},"body":""}
{"type":"http_resp","id":"uuid","status":200,"headers":{},"body":"b2s="}
{"type":"ws_connect","id":"chan","path":"/ws","headers":{}}
{"type":"ws_message","id":"chan","data":"...","binary":false}
{"type":"ping","id":"x","timestamp":0}
{"type":"pong","id":"x","timestamp":0}
```

关键约束：

- 帧是 TEXT JSON，不是裸 HTTP、不是 binary frame。
- SDK 默认 `YR_GATEWAY_TLS=0` 时使用 `ws://`，不携带 `YR_TOKEN`。
- `YR_GATEWAY_TLS=1` 时 SDK 可用 `wss://`，但 frontend/router/tunnel 仍不会把平台 token 转给 tunnel server。

---

## 9. SDK 环境变量与 URL 生成

| 环境变量 | 默认 | 说明 |
|----------|------|------|
| `YR_SERVER_ADDRESS` | 必填 | frontend gateway `host:port`；control API 与 `/direct` 均走这里 |
| `YR_TOKEN` | 必填（SDK 当前要求） | 原始 JWT，放入 `X-Auth` |
| `YR_TLS` | `1` | `1/true/yes` → `https` frontend；`0/false/no` → `http` |
| `YR_GATEWAY_ADDRESS` | 空 | tunnel 和用户端口 URL 的 gateway；为空回退 `YR_SERVER_ADDRESS` |
| `YR_GATEWAY_TLS` | `0` | tunnel 外部连接使用 `wss` 或 `ws` |
| `YR_TUNNEL_CONNECT_TIMEOUT` | `60` | SDK 等待 TunnelClient 连接成功的秒数 |
| `YR_RESUME_CHUNK_SIZE` | `8388608` | resumable file upload 每个 chunk 的默认大小 |
| `YR_RESUME_MAX_RETRIES` | `3` | resumable file upload/download 单次操作内的最大恢复重试次数 |

SDK URL 规则：

| SDK 能力 | URL |
|----------|-----|
| create/delete/frontend invoke | `{http(s)}://{YR_SERVER_ADDRESS}/api/sandbox/v1/sandboxes...` |
| direct invoke | `{http(s)}://{YR_SERVER_ADDRESS}/direct/{safeID}/invoke`，SDK 自动携带 requestId |
| direct upload/download | `{http(s)}://{YR_SERVER_ADDRESS}/direct/{safeID}/upload|download`；file copy 使用 resumable status/chunk/commit 与 Range 下载 |
| reverse tunnel client | `{ws(s)}://{YR_GATEWAY_ADDRESS or YR_SERVER_ADDRESS}/tunnel/{safeID}` |
| sandbox 内访问 reverse tunnel | `http://127.0.0.1:8766`（或 create 响应 `tunnel.proxyUrl`） |
| 用户端口 | `http://{YR_GATEWAY_ADDRESS or YR_SERVER_ADDRESS}/{safeID}/{port}` |

---

## 10. Python SDK 示例

```python
import os
from yr import Sandbox

os.environ["YR_SERVER_ADDRESS"] = "cluster.example.com:8888"
os.environ["YR_GATEWAY_ADDRESS"] = "cluster.example.com:8888"
os.environ["YR_TLS"] = "1"
os.environ["YR_GATEWAY_TLS"] = "0"
os.environ["YR_TOKEN"] = "<jwt>"

with Sandbox(name="demo", cpu=1000, memory=2048) as sb:
    sb.files.write("/tmp/a.txt", "hello")
    print(sb.commands.run("cat /tmp/a.txt").stdout)
    sb.files.copy_from_local("./local-dir", "/work/dir")
```

Reverse tunnel：

```python
with Sandbox(upstream="127.0.0.1:8000") as sb:
    url = sb.get_tunnel_url()  # http://127.0.0.1:8766
    print(sb.commands.run(f"curl -s {url}/health").stdout)
```

用户端口转发：

```python
with Sandbox(port_forwardings=[8080]) as sb:
    sb.commands.run("python3 -m http.server 8080", background=True)
    print(sb.get_port_url(8080))  # http://<gateway>/<safeID>/8080
```

---

## 11. 已知边界

- `cwd` 目前可由 SDK 放入 create body，但 frontend `CreateV1Request` 不消费；请使用 `commands.run(..., cwd=...)` 或 `shells.create(cwd=...)`。
- `Sandbox.delete(name)` 实际按 sandbox id 删除；尚无 name → id 查询接口。
- 用户端口 URL 当前由 SDK 拼接为 `http://<gateway>/<safeID>/<port>`；如果部署层按 HTTPS 暴露用户端口，需要后续在 SDK/配置中表达 per-port scheme。
