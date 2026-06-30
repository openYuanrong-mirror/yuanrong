# 异步调用

## 概述

支持异步调用模式，允许发起请求后立即返回，通过请求 ID 查询执行结果。

## 异步调用流程

    1. 发起异步调用 → 返回 requestId
    2. 立即响应 → 客户端继续其他任务
    3. 服务端处理中...
    4. 通过 requestId 查询结果

## 接口说明

### 发起异步调用

通过在请求头中添加 `X-Invoke-Type: async` 触发异步模式。

```bash
# CLI 异步调用
yrcli invoke --async my_function --payload '{"data": "test"}'

# REST API - 短路径
POST /invocations/<tenant-id>/<namespace>/<function-name>/
Header: X-Invoke-Type: async

# REST API - 标准路径
POST /serverless/v1/functions/<function-urn>/invocations
Header: X-Invoke-Type: async
```

**响应**（HTTP 202）：

```json
{
  "requestId": "req-abc-123"
}
```

### 查询结果

```bash
# CLI 查询
yr result req-abc-123

# REST API
GET /serverless/v1/functions/async-results/<request-id>
```

**响应**：

```json
{
  "requestId": "req-abc-123",
  "status": "completed",
  "result": {...},
  "createdAt": "2026-03-25T10:00:00Z",
  "completedAt": "2026-03-25T10:00:05Z"
}
```

### 状态说明

| 状态 | 说明 |
|------|------|
| queued | 请求已排队 |
| processing | 正在处理 |
| completed | 执行完成 |
| failed | 执行失败 |

## 短 URL 支持

异步调用支持短 URL 路由，简化客户端调用：

    /async/invoke/<tenant>/<function-name>

替代原来的完整路径格式。

## Python SDK

```python
import yr

# 发起异步调用
result = yr.invoke("my_function", data, async_=True)
request_id = result["requestId"]

# 查询结果
while True:
    status = yr.get_result(request_id)
    if status["status"] in ("completed", "failed"):
        break
    time.sleep(1)

print(status["result"])
```

## 配置参数

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `asyncInvocation.enabled` | bool | 是否启用异步调用 | true |
| `asyncInvocation.resultRetentionMinutes` | int | 异步结果保留时间（分钟） | 60 |
