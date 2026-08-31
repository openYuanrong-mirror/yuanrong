# 驱动 Agent 实例执行

## 功能介绍

该 API 用于 openYuanrong 集群，对已创建的常驻 agent 实例执行**一次同步调用**，驱动实例内用户 handler 执行一次业务逻辑并返回其返回值。它与 [创建 Agent 实例](./create_agent_instance.md) 配套：create 返回 `instance_id`，调用方拿该 ID 调 invoke 即可驱动实例执行。

一次 invoke 对应一次用户 handler 执行，返回该 handler 的返回值。agent 模型为单实例串行同步，无流式返回。

> **invoke 与 [Agent 实例协议调用通道](./agent_invoke_channels.md) 的区别**：agent_invoke_channels（SSH/WS/HTTP 三条透传通道）把字节原样桥接到沙箱内**任意服务端端口**，对上层协议透明；invoke 则是按 `instanceId` 同步驱动实例内**用户代码入口**执行一次的 HTTP API，返回用户 handler 的返回值。二者正交，可各自独立使用。

## 前置条件

- openYuanrong 集群已部署并 healthy，frontend 已起（`yr start --master`，默认带 frontend）。
- 已通过 [创建 Agent 实例](./create_agent_instance.md) 创建实例并拿到 `instance_id`，实例处于 `RUNNING`。
- 实例内已就绪用户代码：
  - **registered 模式**：注册函数时 `handler`/`codePath` 已传，且 create 请求 `mounts` 把宿主代码目录挂到了 `target == 该 codePath`。
  - **inline 模式**：create 请求 `runtime_spec` 带了 `codePath`+`handler`，且 `mounts` 把宿主代码目录挂到了 `target == runtime_spec.codePath`。
  - 若 create 时未填 `handler`，实例执行的是Agent Executor（adx）自身代码而非用户代码（见 [创建 Agent 实例](./create_agent_instance.md)），invoke 会驱动该 Executor 而非用户 handler。
- 若 `codePath` 目录未就位，实例启动加载阶段即失败，invoke 会路由失败或超时（见错误码与排查）。

## 接口约束

- `instanceId` 必填，为创建实例时返回的 `instance_id`（UUID）。实例不存在、已删除、或刚重启/迁移导致缓存未命中，统一返回 **404**。
- 请求体为**任意业务 JSON**，将作为 event 喂给用户 handler。请求体为空时按 `{}` 处理。
- **同步单值返回**：一次 invoke 对应一次用户 handler 执行，返回该 handler 的返回值，无流式 SSE。
- create 阶段不校验代码目录是否真的就位，只校验字段是否成对；代码未就位会在实例启动或 invoke 时暴露为加载失败/路由超时（见错误码与排查）。`handler` 不填时实例执行Agent Executor 代码，不会报"无用户代码"错误。
- **鉴权**：`/api/agent` 经 frontend 全局鉴权中间件，与 [创建 Agent 实例](./create_agent_instance.md) 及其它函数服务 REST 接口一致。`enable_func_token_auth` 关时默认放行（信任调用方），开时须携带有效 JWT。

## URI

`POST /api/agent/:instanceId/invoke`

## 请求参数

### 请求 Path 参数

| **参数** | **是否必选** | **参数类型** | **描述** |
| -------- | ---------- | ---------- | ----------- |
| instanceId | 是 | string | 实例 ID（创建时返回的 UUID）。 |

### 请求 Header 参数

| **参数**     | **是否必选** | **参数类型** | **描述** |
| ----------- | ---------- | ---------- | ----------- |
| Content-Type | 否 | string | 消息体类型。建议 `application/json`。 |
| tenantId | 否 | string | 租户 ID。缺省 `default`。 |
| X-Trace-Id | 否 | string | 调用方 trace ID。未传则由 frontend 生成并透传至用户 handler。 |
| traceparent | 否 | string | W3C traceparent，用于链路追踪。 |

### 请求 Body 参数

请求体为**任意业务 JSON**，整体作为 event 喂给用户 handler。无固定 schema，由用户 handler 自行约定字段。

## 响应参数

| **名称** | **类型** | **描述** |
| -------- | -------- | -------- |
| code | int | 状态码，`200` 表示成功。成功时 HTTP 状态码为 `200`。 |
| data | any | 用户 handler 的返回值（成功时返回）。 |
| message | string | 失败时返回错误信息。 |

## 示例

### 前置：创建带代码入口的实例

registered 或 inline 模式均可，只要 create 时带齐代码入口并把代码目录挂载就位。以 inline+supervisor 为例（`mounts[0].target` == `runtime_spec.codePath`）：

```bash
curl -s -X POST http://{frontend}:8888/api/agent -H "Content-Type: application/json" -d '{
  "name": "agent-inline",
  "namespace": "dev",
  "runtime_spec": {
    "runtime": "python3.11",
    "sandbox_type": "supervisor",
    "storageType": "local",
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

### 驱动实例执行

```bash
curl -s -X POST http://{frontend}:8888/api/agent/${INSTANCE_ID}/invoke \
  -H "Content-Type: application/json" \
  -d '{"event": "hello", "n": 42}'
```

响应（`data` 为 `demo.handler` 对 event 的返回值）：

```json
{"code":200,"data":{"echo":"hello","doubled":84}}
```

> 示例为内网明文调用、鉴权关闭场景；生产环境建议 `https://` 并开启 `enable_func_token_auth`，请求携带有效 JWT。

### 异常调用

```bash
# invoke 不存在的实例 → 404
curl -s -X POST http://{frontend}:8888/api/agent/not-exist/invoke -d '{}'
# {"code":404,"message":"instance not found: not-exist"}

# inline 只带 handler 不带 codePath 创建后 invoke → 代码目录未就位，实例启动失败
curl -s -X POST http://{frontend}:8888/api/agent/${INSTANCE_ID}/invoke -d '{"x":1}'
# {"code":500,"message":"invoke failed: ..."}  # 实例起不来，路由失败/超时

# inline 不带 handler 创建后 invoke → 执行Agent Executor 自身代码（非用户代码）
curl -s -X POST http://{frontend}:8888/api/agent/${INSTANCE_ID_ADX}/invoke -d '{"event":"hello"}'
# {"code":200,"data":<Agent Executor handle 的返回值>}
```

## 错误码

| **HTTP 状态** | **描述** |
| -------- | -------- |
| 200 | 成功（OK）。`data` 为用户 handler（或Agent Executor）的返回值。 |
| 400 | 错误的请求（Bad Request）。`message` 形如 `failed to build invoke request: ...`（请求体读取失败等）。 |
| 404 | 未找到（Not Found）。实例不存在 / 已删除 / 刚重启迁移导致缓存未命中，`message` 形如 `instance not found: <id>`。 |
| 500 | 内部服务器错误（Internal Server Error）。`message` 形如 `invoke failed: code=<n> err=<runtime 报错>`（实例内执行报错）；或 `invoke failed: <err>`（底层调用失败 / 超时，常见于实例启动加载阶段即失败）。注：不填 `handler` 时实例执行Agent Executor 代码，不会报"无用户代码"错误。 |

## 排查

- **404 `instance not found`**：实例未在缓存中（未创建 / 已删除 / 刚重启迁移）。先 `GET /api/agent/${INSTANCE_ID}` 确认实例存在；若已删除重新 create。
- **500 实例路由失败 / 超时**：实例启动加载阶段就失败（找不到模块，实例起不来）。两种根因：(1) 缺 `codePath`——inline 的 `runtime_spec.codePath` 没传；(2) `codePath` 传了但目录未就位——`mounts` 缺失或 `mounts[].target` 与 `codePath` 不对齐，使容器内该路径为空。检查 `mounts` 里有 `target == codePath` 的挂载，且其 `source` 宿主目录存在、含模块文件。注：不填 `handler` 时实例执行Agent Executor 代码，不会报"无用户代码"错误，无需在此排查 handler。
- **500 `invoke failed: code=...`**：实例内执行报错（用户代码或Agent Executor 代码运行时异常）。registered 模式检查注册函数时 `handler` 是否非空；inline 若不填 `handler` 则执行的是Agent Executor，排查方向为 Executor 代码而非用户 handler。
- **500 返回含 `invalid function`**：实例与执行器元数据不一致（通常因实例异常或迁移）。重新 create 实例后重试。
