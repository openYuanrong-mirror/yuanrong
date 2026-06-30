# Traefik 反向代理

本目录包含 Traefik 的配置，作为 frontend 和 Keycloak 的统一入口，对外只暴露一个端口（默认 `18888`），同时支持 `http` 和 `https`。

## 架构

```
浏览器 → wyc.pc:18888 (yr-traefik)
  ├── /realms/, /resources/, /js/, /welcome/  → yr-keycloak:8080
  └── /（其他所有路径）                        → dev:8888 (frontend)
```

Traefik、Keycloak、frontend 开发容器共享同一个 Docker 网络 `yr-net`，通过容器名互相访问，不依赖宿主机 IP。

## 文件说明

| 文件 | 说明 |
|------|------|
| `docker-compose.yml` | Traefik 容器定义，加入 `yr-net` 网络 |
| `traefik.yml` | 静态配置：入口点、日志、Dashboard |
| `dynamic.yml` | 动态配置：路由规则和后端服务地址 |
| `cert/wyc.pc.crt` | 本地开发使用的自签名证书 |
| `cert/wyc.pc.key` | 本地开发使用的私钥 |
| `traefik-start.sh` | 启动/停止/状态管理脚本 |

## 快速开始

### 前提

共享网络 `yr-net` 必须已创建，且 Keycloak、frontend 容器也已加入该网络：

```bash
# 创建网络（只需一次）
docker network create yr-net
```

### 启动

```bash
./traefik-start.sh start
```

或直接用 compose：

```bash
docker compose up -d
```

### 停止 / 重启 / 状态

```bash
./traefik-start.sh stop
./traefik-start.sh restart
./traefik-start.sh status
```

## 访问地址

| 地址 | 说明 |
|------|------|
| https://wyc.pc:18888 | 统一入口（frontend） |
| https://wyc.pc:18888/realms/yuanrong | Keycloak Realm API |
| http://localhost:8080/admin | Keycloak Admin Console（直连，不经 Traefik）|
| https://wyc.pc:18888/dashboard/ | Traefik Dashboard |

## 路由规则（dynamic.yml）

| 路由 | 匹配规则 | 后端 |
|------|---------|------|
| `keycloak` | `/realms`、`/resources`、`/js`、`/welcome` | `yr-keycloak:8080` |
| `frontend` | `/`（其他所有） | `dev:8888` |
| `dashboard` | `/dashboard`、`/api` | Traefik 内置 |

优先级：dashboard(100) > keycloak(10) > frontend(1)

## 与完整开发环境的启动顺序

```bash
# 1. 创建共享网络（只需一次）
docker network create yr-net

# 2. 启动 Keycloak
cd example/keycloak
KEYCLOAK_PUBLIC_URL=https://wyc.pc:18888 ./start-keycloak.sh start

# 3. 启动 Traefik
cd example/traefik
./traefik-start.sh start

# 4. 启动 frontend 开发容器（如还未启动）
cd /home/wyc/code/dev
docker compose up -d

# 5. 初始化 Keycloak realm（首次）
cd example/keycloak
./init-realm.sh

# 6. 在开发容器里启动运行时
./example/restart.sh token
```

## 故障排查

### 502 Bad Gateway

后端容器未加入 `yr-net`，或容器名不匹配。检查：

```bash
docker network inspect yr-net
```

确认 `yr-keycloak` 和 `dev` 都在其中。若缺失，手动加入：

```bash
docker network connect yr-net yr-keycloak
docker network connect yr-net dev
```

### HTTPS 证书提示不受信任

`example/traefik/cert/wyc.pc.crt` 是仓库内置的本地自签名证书，重启后不会丢，但浏览器默认不会信任。

如需消除浏览器告警，请把该证书导入系统或浏览器信任列表。

### Traefik Dashboard 无法访问

访问 `https://wyc.pc:18888/dashboard/`（注意末尾的 `/`）。

### 修改路由规则后未生效

`dynamic.yml` 配置了 `watch: true`，Traefik 会自动热加载，无需重启。稍等几秒后重试。
