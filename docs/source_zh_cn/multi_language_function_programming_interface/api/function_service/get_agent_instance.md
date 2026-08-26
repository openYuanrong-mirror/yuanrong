# 查询单个 Agent 实例

## 功能介绍

该 API 用于 openYuanrong 集群，查询单个 agent 实例的详细状态。按 `instanceId` 直达，返回该实例的身份信息、运行地址、容器地址及创建时的配置（rootfs/端口/环境变量/资源/启动时间），供运维定位与排障。

数据来源于 frontend 本地的实例缓存（execendpoint watcher），**只反映当前缓存中存在的 RUNNING 实例**。实例被删除或尚未进入 RUNNING 缓存时返回 404。查询接口与创建/删除接口一样不区分 inline / registered 两种创建模式。

## 接口约束

- `instanceId` 必须为创建 agent 实例返回的 `instance_id`（UUID）。`GET /api/agent/`（末段为空）路由到 [查询 Agent 实例列表](./list_agent_instance.md) 而非本接口，故本接口内 `instanceId` 不会为空。
- 不存在、已删除或尚未进入 RUNNING 缓存的 `instanceId` 返回 404——这是有意行为：查询接口只描述当前真实存在的实例，不构造不存在的视图。
- 鉴权遵循 frontend 全局 `GlobalJwtAuthMiddleware`，与其它函数服务 REST API 一致。`enable_func_token_auth` 开时须携带有效 JWT（见 [Agent 实例协议调用通道](./agent_invoke_channels.md) 鉴权说明）。
- 响应字段受 `omitempty` 控制：未配置端口/环境变量/rootfs 时对应字段缺省不返回。客户端按字段存在性容错，不要假定全字段必填。

## URI

`GET /api/agent/:instanceId`

## 请求参数

### 请求 Path 参数

| **参数** | **是否必选** | **参数类型** | **描述** |
| -------- | ---------- | ---------- | ----------- |
| instanceId | 是 | string | 实例 ID（创建时返回的 UUID）。 |

### 请求 Header 参数

| **参数**     | **是否必选** | **参数类型** | **描述** |
| ----------- | ---------- | ---------- | ----------- |
| tenantId | 否 | string | 租户 ID。查询按 `instanceId` 全局直达，`tenantId` 不参与实例过滤，缺省 `default`。 |

## 响应参数

响应体 `code` 字段 `200` 表示成功，详细实例信息置于 `instance` 对象。

| **名称** | **类型** | **描述** |
| -------- | -------- | -------- |
| code | int | 状态码，`200` 表示成功。成功时 HTTP 状态码为 `200`。 |
| instance | Object | 实例详情。失败时不返回。 |
| message | String | 失败时返回错误信息。 |

### instance 对象

| **名称** | **类型** | **描述** |
| -------- | -------- | -------- |
| instance_id | String | 实例 ID（UUID）。 |
| node_ip | String | 宿主节点 IP（由 owner proxy gRPC 地址提取）。 |
| sandbox_ip | String | 容器内网 IP（docker inspect 或 supervisor create 响应）。实例未分配内网 IP 时缺省不返回。 |
| sandbox_type | String | executor 类型，取值 `docker` / `supervisor`，来自 createOptions["sandbox_type"]。 |
| sandbox_id | String | 容器/沙箱 ID（docker containerID 或 supervisor/runsc sandboxID）。 |
| rootfs | Object | rootfs 详情。见 rootfs 对象。未配置时缺省不返回。 |
| ports | array | 端口转发标签，格式 `<proto>:<port>`（如 `tcp:22`），来自 createOptions["network"]。未配置时缺省不返回。 |
| env_vars | map | 注入容器的动态环境变量，来自 createOptions["DELEGATE_ENV_VAR"]。未配置时缺省不返回。 |
| resources | map | 资源用量（标量值）。`CPU` 单位 `1/1000` 核；`storage` 内部按字节存储，对外折算为 MiB（`bytes ÷ (1024×1024)`）。 |
| start_time | String | 实例启动时间（RFC3339，来自 service 端）。service 端缺失时回退为 watcher 首次观测到 RUNNING 的本地时间。 |

#### rootfs 对象

| **名称** | **类型** | **描述** |
| -------- | -------- | -------- |
| type | String | rootfs 类型，docker 镜像为 `image`。 |
| imageurl | String | docker 镜像引用（如 `yr-docker-runtime:v0`）。 |
| user | String | 容器 run-as 用户，来自 createOptions["host_user"]。 |
| workspace | String | 宿主 workspace 绝对路径（创建时 `workspace` 入参），来自 createOptions["workspace"]，与 rootfs JSON 中的 workspace 挂载区分。 |
| mounts | array | 额外 bind mount 列表。见 mount 对象。 |

#### mount 对象

| **名称** | **类型** | **描述** |
| -------- | -------- | -------- |
| source | String | 宿主机绝对路径。 |
| target | String | 容器内路径。 |
| readonly | boolean | 是否只读。`false` 亦显式返回。 |

## 示例

```bash
curl http://{frontend}:8888/api/agent/0b6c6322-6533-4901-8000-00000000bb0b
# 开启鉴权时携带：-H "X-Auth: <jwt>"
```

> 示例为内网明文调用、鉴权关闭场景；生产环境建议 `https://` 并开启 `enable_func_token_auth`，请求携带有效 JWT。

响应（docker 实例，完整字段）：

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

supervisor 实例（无 rootfs/ports）：

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

## 错误码

| **HTTP 状态** | **描述** |
| -------- | -------- |
| 200 | 成功（OK）。返回实例详情。 |
| 401 | 未认证（Unauthorized）。`enable_func_token_auth` 开启时未携带或 JWT 无效，由全局 `GlobalJwtAuthMiddleware` 在进入 handler 前返回。 |
| 403 | 禁止（Forbidden）。JWT 有效但调用方无权限。 |
| 404 | 未找到（Not Found）。`instanceId` 不存在、已删除或尚未进入 RUNNING 缓存；`message` 为 `instance not found or not running`。 |
