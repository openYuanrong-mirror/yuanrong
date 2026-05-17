# WebSocket Transport 设计与实现

## 概述

为 GwClient 添加 WebSocket 传输层，复用单条长连接进行 create/invoke 操作，避免 HTTP 短连接开销。使用二进制帧协议直接传输 protobuf，无 JSON/base64 编解码损耗。

## 设计目标

1. **抽象传输层**: `TransportClient` 接口统一 HTTP 和 WebSocket
2. **二进制帧协议**: WebSocket BinaryMessage 直传 protobuf，零序列化开销
3. **自动降级**: WS 未启用或连接失败时回退 HTTP，对上层透明
4. **断连恢复**: 后台定时重连 + 在途请求自动 drain 错误回调
5. **长任务支持**: 无 per-request 超时，支持任意时长的 create/invoke

## 架构

```text
┌─────────────────────────────────────────────────────────────┐
│               libruntime_manager.cpp                        │
│  gwClient->Init(httpClient, timeout, authToken)             │
│  gwClient->SetWsTransport(CreateWsTransportFromConfig(cfg)) │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                       GwClient                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              selectTransport()                        │  │
│  │  WS enabled && connected? ──► wsTransport_           │  │
│  │  otherwise             ? ──► httpTransport_          │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
           ┌───────────────┴───────────────┐
           ▼                               ▼
┌──────────────────────┐       ┌──────────────────────────┐
│   HttpTransport      │       │      WsTransport         │
│  (HttpClient 包装)    │       │  (Boost.Beast WebSocket) │
│                      │       │  ReadLoop / WriteLoop /  │
│                      │       │  TimeoutCheckLoop        │
└──────────────────────┘       └──────────────────────────┘
           │                               │
           ▼                               ▼
┌─────────────────────────────────────────────────────────────┐
│                       Frontend (Go)                         │
│  ┌──────────────────┐       ┌────────────────────────────┐  │
│  │  HTTP Handlers   │       │  /serverless/v1/posix/ws   │  │
│  │  (gin routes)    │       │  gorilla/websocket         │  │
│  │                  │       │  JWT auth + binary frames  │  │
│  └──────────────────┘       └────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 配置项

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `YR_ENABLE_WEBSOCKET` | 是否启用 WebSocket 传输 | `false` |
| `YR_WEBSOCKET_TIMEOUT` | WS Init 超时 (秒) | `30` |
| `YR_WEBSOCKET_RECONNECT_INTERVAL` | 后台重连间隔 / 心跳 ping 间隔 (秒) | `5` |

TLS、证书、服务器地址从 `LibruntimeConfig` 字段获取（与 HTTP 传输共享配置），不再从环境变量单独读取：

| LibruntimeConfig 字段 | 用途 |
|----------------------|------|
| `functionSystemIpAddr` / `functionSystemPort` | WS 连接目标 (与 HTTP 相同) |
| `enableTLS` / `enableMTLS` | TLS 开关 |
| `certificateFilePath` / `privateKeyPath` / `verifyFilePath` | 证书文件 |
| `authToken` | JWT token，通过 Beast decorator 注入 WS 握手 `X-Auth` header |

> `YR_WEBSOCKET_ENDPOINT` 已废弃，保留定义但不再使用。

## C++ 端实现

### 线程模型

WsTransport 启动 3 个后台线程：

| 线程 | 职责 |
|------|------|
| **ReadLoop** | 阻塞读 WS 帧 → 解析二进制响应 → 匹配 requestId → 触发回调。断连时 wait on `reconnectCv_` |
| **WriteLoop** | 从 `writeQueue_` 取帧 → 写入 WS。未连接时 fire error callback |
| **TimeoutCheckLoop** | 已连接：定时发 ping 心跳；断连：定时尝试后台重连 |

### 初始化流程

```text
libruntime_manager.cpp
  └─ CreateWsTransportFromConfig(librtConfig)     // 静态工厂
       ├─ 检查 YR_ENABLE_WEBSOCKET
       ├─ 从 LibruntimeConfig 提取 host/port/TLS/cert/token
       ├─ WsTransport::Init(TransportParam)
       │    ├─ Connect() — TCP → (TLS handshake) → WS handshake
       │    │   └─ Beast decorator 注入 X-Auth header
       │    └─ 启动 ReadLoop / WriteLoop / TimeoutCheckLoop
       └─ 返回 shared_ptr<TransportClient> 或 nullptr
  └─ gwClient->SetWsTransport(ws)
```

### 请求流程

```text
GwClient::CreateAsync / InvokeAsync
  └─ selectTransport()  →  wsTransport_ (if connected) / httpTransport_ (fallback)
  └─ SubmitRequest(target, headers, body, requestId, callback)
       ├─ 构建二进制帧: [version][opCode][idLen][id][protobuf]
       ├─ 注册 callback 到 pendingCallbacks_[requestId]
       └─ 入队 writeQueue_ → WriteLoop 发送
```

### 断连与重连

- **ReadLoop** 检测读错误 → `connected_ = false` → `DrainPendingCallbacks()` (仅 `running_` 时)
- **TimeoutCheckLoop** 发现 `!connected_` → 按 `YR_WEBSOCKET_RECONNECT_INTERVAL` 间隔重试 `Connect()`
- **Connect()** 成功后 `connected_ = true` + `reconnectCv_.notify_all()` → ReadLoop 恢复
- **SubmitRequest** 发现未连接时也会尝试即时重连 (快速路径)

### 正常关闭

```text
WsTransport::Stop()
  ├─ running_ = false
  ├─ notify writeCv_ / reconnectCv_ → 唤醒所有等待线程
  ├─ ws_->close() (仅 connected_ 时，避免未完成握手的 stream 阻塞)
  ├─ join ReadLoop / WriteLoop / TimeoutCheckLoop
  └─ 清理残余 pendingCallbacks_ (投机 create 等预期场景)
```

## Go Frontend 端实现

### 路由

```go
r.GET("/serverless/v1/posix/ws", gin.WrapF(posixws.HandlePosixWebSocket))
```

### 认证

`authenticateWebSocket()` 从多个来源获取 JWT token：

1. `X-Auth` header (C++ Beast decorator 注入)
2. `?token=` query parameter
3. `iam_token` cookie
4. `Sec-WebSocket-Protocol` subprotocol (浏览器 WebSocket 场景)

认证通过后提取 `tenantID`，注入到后续所有请求的 header 中。

### 消息处理

```go
func (s *Session) run() {
    // 设置 60s 读超时，由 PongHandler/PingHandler 持续重置
    s.conn.SetReadDeadline(time.Now().Add(60s))
    s.conn.SetPongHandler(...)   // 重置 read deadline
    s.conn.SetPingHandler(...)   // 回复 Pong + 重置 read deadline

    for {
        messageType, message, err := s.conn.ReadMessage()
        go s.handleMessage(messageType, message)  // 异步处理，不阻塞读循环
    }
}
```

- **BinaryMessage** → `handleBinaryMessage()`: 解析二进制帧头，直传 protobuf 到 processor
- **TextMessage** → JSON 解析，兼容旧协议

### Processor

| 方法 | 说明 |
|------|------|
| `ProcessCreateRaw(payload []byte, headers)` | 二进制路径：直接转发 protobuf，跳过 base64 |
| `ProcessInvokeRaw(payload []byte, headers)` | 同上 |
| `ProcessCreate(payload map, headers)` | JSON 路径：base64 解码后转发 |
| `ProcessInvoke(payload map, headers)` | 同上 |

## 二进制帧协议

### 请求帧 (C++ → Frontend)

```text
Byte 0:      版本号 (0x01)
Byte 1:      操作码 (0x01=create, 0x02=invoke)
Byte 2-3:    请求ID长度 (uint16 大端)
Byte 4..N:   请求ID (UTF-8)
Byte N+1..:  原始 protobuf 载荷
```

### 响应帧 — 成功 (Frontend → C++)

```text
Byte 0:      版本号 (0x01)
Byte 1:      状态码 (0x00=成功)
Byte 2-3:    请求ID长度 (uint16 大端)
Byte 4..N:   请求ID (UTF-8)
Byte N+1..:  原始 protobuf 响应
```

### 响应帧 — 错误 (Frontend → C++)

```text
Byte 0:      版本号 (0x01)
Byte 1:      状态码 (0x01=错误)
Byte 2-3:    请求ID长度 (uint16 大端)
Byte 4..N:   请求ID (UTF-8)
Byte N+1..N+4: 错误码 (int32 大端)
Byte N+5..:  错误消息 (UTF-8)
```

### JSON 文本协议 (向后兼容)

Frontend 同时支持 TextMessage 的 JSON 协议，用于旧版客户端或调试：

**请求:**

```json
{
  "type": "request",
  "id": "uuid",
  "operation": "create | invoke",
  "payload": "base64-encoded-protobuf",
  "headers": {"remoteClientId": "xxx"}
}
```

**响应:**

```json
{
  "type": "response",
  "id": "uuid",
  "status": "success | error",
  "payload": "base64-encoded-protobuf",
  "error": {"code": 1005, "message": "..."}
}
```

**控制消息:**

```json
{"type": "ping | pong", "timestamp": 1712836800}
```

## 实现文件

### C++ Runtime

| 文件 | 说明 |
|------|------|
| `src/libruntime/gwclient/transport/transport_client.h` | TransportClient 抽象接口 + TransportParam |
| `src/libruntime/gwclient/transport/http_transport.h/cpp` | HttpClient 适配器 |
| `src/libruntime/gwclient/transport/ws_transport.h/cpp` | WebSocket 实现 + `CreateWsTransportFromConfig` 工厂 |
| `src/libruntime/gwclient/gw_client.h/cpp` | `SetWsTransport()` + `selectTransport()` 路由 |
| `src/libruntime/libruntime_manager.cpp` | 初始化入口：调用工厂创建 WS 并注入 GwClient |
| `src/dto/config.h` | `YR_ENABLE_WEBSOCKET` / `YR_WEBSOCKET_TIMEOUT` / `YR_WEBSOCKET_RECONNECT_INTERVAL` |
| `test/libruntime/ws_transport_test.cpp` | 二进制帧编解码单元测试 |

### Go Frontend

| 文件 | 说明 |
|------|------|
| `frontend/pkg/frontend/posixws/handler.go` | WS 连接管理、认证、消息分发 |
| `frontend/pkg/frontend/posixws/processor.go` | create/invoke 请求处理 (Raw + JSON 双路径) |
| `frontend/pkg/frontend/posixws/message.go` | 二进制帧协议常量、构建/解析函数 |
| `frontend/pkg/frontend/posixws/message_test.go` | Go 侧二进制帧单元测试 |
| `frontend/pkg/frontend/api/api.go` | 路由注册 `/serverless/v1/posix/ws` |

## 使用方式

```bash
export YR_ENABLE_WEBSOCKET=true
# 服务器地址、TLS、证书等使用与 HTTP 相同的配置
```

## 已知行为

- 调度器投机发送 N 个 create 请求，实际可能只需 1 个实例。未使用的 create 在 `Stop()` 时被清理，属预期行为
- `HttpTransport::Init(TransportParam)` 存在但未被调用（HttpTransport 始终以 wrapper 模式构造），保留仅为满足接口约束
