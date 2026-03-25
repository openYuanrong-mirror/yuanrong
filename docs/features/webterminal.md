# WebTerminal

## 概述

基于 WebSocket 的浏览器终端，支持多窗口、JWT 认证和 PTY 交互。

## 架构

    浏览器 (xterm.js)
        │
        ▼ WebSocket
    ┌─────────────┐
    │  Frontend   │
    │  WebTerminal│ ◄── JWT Auth
    │  Handler    │
    └─────────────┘
        │
        ▼ gRPC Bidirectional Stream
    ┌─────────────┐
    │ Function    │
    │ Proxy       │
    │ ExecStream  │
    └─────────────┘
        │
        ▼ docker exec PTY
    ┌─────────────┐
    │  Container  │
    │  (Runtime)  │
    └─────────────┘

## WebSocket 接口

### 连接建立

    ws://host:port/terminal?token=<JWT>&function=<function_name>

| 参数 | 类型 | 说明 |
|------|------|------|
| token | string | JWT 认证 Token |
| function | string | 函数名称 |
| instance_id | string | 实例 ID（可选） |

### 子协议

通过 `Sec-WebSocket-Protocol` 传递 JWT：

    Sec-WebSocket-Protocol: <JWT>

## 消息格式

### 请求消息（浏览器 → 服务端）

```json
{
  "type": "input",
  "data": "ls -la\n",
  "rows": 24,
  "cols": 80
}
```

### 响应消息（服务端 → 浏览器）

**响应**：

```json
{
  "type": "output",
  "data": "total 32\ndrwxr-xr-x  2 root user 4096 Mar 25 10:00 .\n"
}
```

### 消息类型

| 类型 | 方向 | 说明 |
|------|------|------|
| input | → | 终端输入 |
| output | ← | 终端输出 |
| resize | → | 终端大小调整 |
| heartbeat | ↔ | 心跳保活 |
| error | ← | 错误信息 |
| close | ↔ | 关闭连接 |

## JWT 认证

### Token 载荷

**载荷**：

```json
{
  "sub": "user-123",
  "tenant_id": "tenant-abc",
  "function_name": "my-func",
  "exp": 1700000000
}
```

### 认证流程

1. 浏览器连接时携带 JWT
2. Frontend 验证 Token 有效性
3. 验证通过后建立 WebSocket 连接
4. 周期发送 heartbeat 保持连接

## 配置参数

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `webterm.enabled` | bool | 是否启用 WebTerminal | true |
| `webterm.port` | int | WebSocket 端口 | 8888 |
| `webterm.keepalive` | int | 保活时间（秒） | 3600 |
| `webterm.heartbeat_interval` | int | 心跳间隔（秒） | 30 |
| `webterm.path_prefix` | string | URL 路径前缀 | /terminal |

## 权限控制

### 角色权限

| 角色 | WebTerminal 权限 |
|------|------------------|
| admin | 所有函数的终端 |
| developer | 自己的函数终端 |
| operator | 只读终端 |

### 函数级权限

```yaml
webterm:
  allowed_functions:
    - "my-func-1"
    - "my-func-2"
  denied_functions:
    - "admin-func"
```

## 多窗口支持

每个浏览器标签页对应独立的 PTY 会话：

    标签页 1 ──▶ Session A ──▶ Instance 1
    标签页 2 ──▶ Session B ──▶ Instance 2

### 会话管理

| 操作 | 说明 |
|------|------|
| 创建会话 | 首次连接时自动创建 |
| 复用会话 | 相同 instance_id 复用现有会话 |
| 关闭会话 | 关闭标签页或显式关闭 |

## Sandbox 集成

WebTerminal 也支持 Sandbox 模式的终端：

    ws://host:port/sandbox/terminal?token=<JWT>

响应消息增加 sandbox 相关字段：

**响应**：

```json
{
  "type": "output",
  "data": "sandbox $ ",
  "sandbox_id": "sb-123"
}
```

## 日志位置

    /tmp/yr_sessions/latest/log/
    ├── faasfrontend.so-run.<pid>.log    # Frontend 日志
    └── <pid>-function_proxy.log         # Proxy 日志
