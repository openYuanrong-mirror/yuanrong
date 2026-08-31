# 查询 Agent 实例列表

## 功能介绍

该 API 用于 openYuanrong 集群，查询当前所有 agent 实例的简要视图。返回缓存中每个 RUNNING 实例的身份信息与运行/容器地址，用于全局巡检与多实例导航。

数据来源于 frontend 本地的实例缓存（execendpoint watcher），**只反映当前缓存中存在的 RUNNING 实例**。列表按 `instance_id` 排序。系统内部驱动（driver-frontend/driver-scheduler 等，无 `sandbox_type`）会被过滤，不计入用户 agent 实例。无实例时返回空数组，而非 404。

## 接口约束

- 无请求参数：列表返回缓存中全部用户 agent 实例，不按 `tenantId` 过滤（`tenantId` 仅由鉴权中间件用于校验，不参与实例筛选）。
- 列表是**简要视图**（identity + 地址），不含创建配置；需单实例详情调 [查询单个 Agent 实例](./get_agent_instance.md)。
- 鉴权遵循 frontend 全局 `GlobalJwtAuthMiddleware`，与其它函数服务 REST API 一致。`enable_func_token_auth` 开时须携带有效 JWT（见 [Agent 实例协议调用通道](./agent_invoke_channels.md) 鉴权说明）。
- 响应字段受 `omitempty` 控制：实例未分配内网 IP 时 `sandbox_ip` 缺省不返回。客户端按字段存在性容错，不要假定全字段必填。

## URI

`GET /api/agent`

## 请求参数

### 请求 Header 参数

| **参数**     | **是否必选** | **参数类型** | **描述** |
| ----------- | ---------- | ---------- | ----------- |
| tenantId | 否 | string | 租户 ID。仅由鉴权中间件校验，不参与实例过滤，缺省 `default`。 |

无请求 Body / Path 参数。

## 响应参数

响应体 `code` 字段 `200` 表示成功，实例简要信息置于 `instances` 数组。无实例时 `instances` 为空数组 `[]`。

| **名称** | **类型** | **描述** |
| -------- | -------- | -------- |
| code | int | 状态码，`200` 表示成功。 |
| instances | array | 实例简要列表，按 `instance_id` 排序。 |

### instances 元素

| **名称** | **类型** | **描述** |
| -------- | -------- | -------- |
| instance_id | String | 实例 ID（UUID）。 |
| node_ip | String | 宿主节点 IP（由 owner proxy gRPC 地址提取）。 |
| sandbox_ip | String | 容器内网 IP（docker inspect 或 supervisor create 响应）。实例未分配内网 IP 时缺省不返回。 |
| sandbox_type | String | executor 类型，取值 `docker` / `supervisor`，来自 createOptions["sandbox_type"]。 |

## 示例

```bash
curl http://{frontend}:8888/api/agent
# 开启鉴权时携带：-H "X-Auth: <jwt>"
```

> 示例为内网明文调用、鉴权关闭场景；生产环境建议 `https://` 并开启 `enable_func_token_auth`，请求携带有效 JWT。

响应（含 docker + supervisor 各一）：

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

无实例时：

```json
{"code":200,"instances":[]}
```

## 错误码

| **HTTP 状态** | **描述** |
| -------- | -------- |
| 200 | 成功（OK）。返回实例简要列表（无实例时 `instances` 为空数组）。 |
| 401 | 未认证（Unauthorized）。`enable_func_token_auth` 开启时未携带或 JWT 无效，由全局 `GlobalJwtAuthMiddleware` 在进入 handler 前返回。 |
| 403 | 禁止（Forbidden）。JWT 有效但调用方无权限。 |
