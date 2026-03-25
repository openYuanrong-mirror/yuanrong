# Traefik 路由

## 概述

Traefik 作为 API 网关入口，负责请求路由和负载均衡。请求链路为：

    Client → Traefik → Frontend → FunctionProxy → Runtime

## 架构组件

### 组件职责

| 组件 | 职责 |
|------|------|
| Traefik | HTTP 网关入口，动态路由，负载均衡 |
| Frontend | 请求转发，认证鉴权 |
| FunctionProxy | 函数调度，实例管理 |
| Runtime | 函数运行时环境 |

### 请求流程

    用户请求
        │
        ▼
    Traefik (HTTP 路由)
        │
        ├── /api/*        → Frontend (API 路由)
        ├── /terminal/*    → Frontend (WebSocket 终端)
        └── /<instance-id>-<port>/* → Runtime HTTP 服务
                                           │
                                           ▼
                                      FunctionProxy
                                           │
                                           ▼
                                        Runtime

## 端口转发机制

Runtime 实例暴露的 HTTP 服务通过端口转发机制对外访问。

### 流程

1. **创建 Runtime 时**：通过 option 传入转发配置（instance-id 和端口）
2. **FunctionProxy**：将转发规则写入 etcd
3. **Traefik**：从 etcd 动态获取路由规则
4. **用户访问**：`http://traefik/<instance-id>-<port>/<path>`

### 配置示例

创建 Runtime 时指定端口转发：

```bash
yr runtime create \
    --name my-runtime \
    --expose-port 8080
```

### etcd 路由存储

FunctionProxy 将路由规则写入 etcd：

```bash
# 路由规则格式
/traefik/routes/<instance-id>-<port>:
{
  "backend": "http://<runtime-ip>:<port>",
  "rule": "PathPrefix:/<instance-id>-<port>"
}
```

### Traefik 配置

Traefik 启用 etcd 作为动态配置源：

```yaml
# etcd 配置
etcd:
  endpoint: "etcd:2379"
  prefix: "/traefik"

# 路由规则示例
http:
  routers:
    runtime-route:
      rule: "PathPrefix(`/<instance-id>-<port>`)"
      service: runtime-backend
  services:
    runtime-backend:
      loadBalancer:
        servers:
          - url: "http://<runtime-ip>:<port>"
```

## 用户访问方式

### 访问 Runtime HTTP 服务

    # 格式
    http://<host>/<instance-id>-<port>/<service-path>

    # 示例
    http://traefik/instance-abc123-8080/api/v1/data

### 访问链路说明

1. 请求到达 Traefik
2. Traefik 根据 `<instance-id>-<port>` 匹配路由规则
3. 规则指向对应 Runtime 实例的 IP:端口
4. 请求转发到 Runtime

## 动态路由更新

### FunctionProxy 写入 etcd

```bash
# 写入路由规则
etcdctl put /traefik/routes/instance-abc123-8080 \
  '{"backend":"http://10.0.0.5:8080","rule":"PathPrefix:/instance-abc123-8080"}'

# 删除路由规则 (实例销毁时)
etcdctl del /traefik/routes/instance-abc123-8080
```

### 路由生命周期

| 阶段 | 操作 |
|------|------|
| Runtime 创建 | FunctionProxy 分配 instance-id 和端口，写入 etcd |
| Runtime 运行 | Traefik 通过 etcd 感知路由规则 |
| Runtime 销毁 | FunctionProxy 删除 etcd 中的路由规则 |

## 与 Frontend 的关系

Traefik **不替代** Frontend：

- **Traefik**：负责 HTTP 入口路由，将请求分发到不同后端服务
- **Frontend**：负责 API 认证、WebSocket 终端、函数管理等业务逻辑

请求根据路径分流：

    /api/*        → Frontend (Go)
    /terminal/*   → Frontend (WebSocket)
    /*-*/        → Runtime (通过 Traefik 直接访问)
