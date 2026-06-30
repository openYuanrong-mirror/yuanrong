# Keycloak 本地开发环境

本目录包含用于本地开发和测试的 Keycloak 配置。Keycloak 通过 `docker compose` 启动，与 Traefik、frontend 开发容器共享同一个 Docker 网络 `yr-net`。

## 架构概览

```
浏览器 → wyc.pc:18888 (yr-traefik)
  ├── /realms/, /resources/, /js/ → yr-keycloak:8080  （容器名直连）
  └── /（其他）                   → dev:8888           （frontend 开发容器）

dev 容器里 Go 代码 → yr-keycloak:8080  （容器名直连，不经外部 IP）
```

## 快速开始

### 0. 创建共享网络（只需一次）

```bash
docker network create yr-net
```

### 1. 启动所有服务

```bash
# Keycloak（通过 Traefik 对外暴露）
cd example/keycloak
KEYCLOAK_PUBLIC_URL=http://wyc.pc:18888 ./start-keycloak.sh start

# Traefik（统一入口，监听 18888）
cd example/traefik
docker compose up -d

# frontend 开发容器（如还未启动）
cd /home/wyc/code/dev
docker compose up -d
```

### 2. 初始化 Realm 和 Client

```bash
cd example/keycloak
./init-realm.sh
```

这将创建：
- `yuanrong` realm
- `frontend` confidential client，secret 写入 `example/keycloak/.keycloak.env`
- 测试用户和角色
- 开启自助注册（`registrationAllowed=true`）

### 3. 启动 frontend 运行时

```bash
./example/restart.sh token
```

`restart.sh` 会自动加载 `.keycloak.env` 中的 secret，无需手动配置。

环境变量默认值：
- `KEYCLOAK_URL=http://wyc.pc:18888`（浏览器侧公开地址）
- `KEYCLOAK_INTERNAL_URL=http://yr-keycloak:8080`（服务端直连 Keycloak）

### 4. 测试认证流程

```bash
# 完整测试
./test-auth.sh all

# 仅测试 token 获取
./test-auth.sh token

# 测试 token 交换
./test-auth.sh exchange
```

## 测试用户

| 用户名 | 密码 | 角色 |
|--------|------|------|
| testuser | test123 | user |
| developer | dev123 | developer |
| testadmin | admin123 | admin |

> 说明：默认已开启 Keycloak 自助注册。你也可以通过前端 `/auth/register-page` 进入注册流程。

## 管理命令

```bash
# 启动
./start-keycloak.sh start

# 停止
./start-keycloak.sh stop

# 重启
./start-keycloak.sh restart

# 状态
./start-keycloak.sh status

# 一键清空并重建本地 Keycloak
./reset-keycloak.sh --force
```

## 访问地址

- Keycloak（内部）: http://localhost:8080
- Keycloak（通过 Traefik）: http://wyc.pc:18888/realms/yuanrong
- Admin Console: http://localhost:8080/admin
- Admin 凭据: admin / admin123

## 数据持久化

Keycloak 数据存储在 `./data/` 目录中。推荐使用：

```bash
./reset-keycloak.sh --force
```

可选参数：
- `--no-start`：只清空，不重启 Keycloak
- `--no-init`：清空并重启，但不执行 `init-realm.sh`

## Client Secret 管理

`init-realm.sh` 每次运行会生成（或复用）一个随机 client secret，并将其写入：

```
example/keycloak/.keycloak.env
```

`restart.sh` 启动时自动 source 此文件，secret 始终保持最新，无需手动维护。

如需固定 secret，运行时指定：

```bash
CLIENT_SECRET=mysecret ./init-realm.sh
```

## 生产环境建议（关闭自助注册）

```bash
REGISTRATION_ALLOWED=false ./init-realm.sh
```

## 角色权限

| 角色 | 权限 |
|------|------|
| admin | 完全管理权限 |
| developer | 函数管理、日志查看 |
| user | 函数调用、日志查看 |
| viewer | 只读 |

## 环境变量

### start-keycloak.sh

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `KEYCLOAK_PUBLIC_URL` | `http://localhost:8080` | Keycloak 公开访问地址（反向代理场景必须设置）|
| `KEYCLOAK_ADMIN` | `admin` | 管理员用户名 |
| `KEYCLOAK_ADMIN_PASSWORD` | `admin123` | 管理员密码 |

### restart.sh（frontend 运行时）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `KEYCLOAK_URL` | `http://wyc.pc:18888` | 浏览器侧公开地址，用于 OAuth2 跳转 |
| `KEYCLOAK_INTERNAL_URL` | `http://yr-keycloak:8080` | 服务端直连 Keycloak（容器名，不经外部 IP）|
| `KEYCLOAK_REALM` | `yuanrong` | Realm 名称 |
| `KEYCLOAK_CLIENT_ID` | `frontend` | Client ID |
| `KEYCLOAK_CLIENT_SECRET` | 从 `.keycloak.env` 加载 | Client secret |

### frontend keycloakConfig 字段说明

| 字段 | 说明 |
|------|------|
| `url` | 公开地址，用于浏览器侧 OAuth2 跳转 |
| `internalUrl` | 内部地址，用于服务端 token 请求（不设置则回退到 `url`）|

## 故障排查

### connection refused 访问 Keycloak

服务端用了公开 IP 访问自己（hairpin NAT 问题）。确认 `KEYCLOAK_INTERNAL_URL` 填的是容器名 `http://yr-keycloak:8080`，且 dev 容器已加入 `yr-net` 网络。

### unauthorized_client

Client secret 不匹配。重新运行 `./init-realm.sh` 刷新 `.keycloak.env`，再重启运行时。

### Cookie not found / We are sorry...

Keycloak 在 HTTP 环境下 `AUTH_SESSION_ID` cookie 带有 `Secure` 标志，浏览器拒绝存储。

解决方案：前端登录页 (`/auth/login-page`) 已改为直接展示用户名/密码表单，通过 password grant（`/auth/token/direct`）直接获取 IAM token，不走 OAuth2 redirect 流程。

### Keycloak 容器未加入 yr-net

```bash
docker network connect yr-net yr-keycloak
```

### 检查容器网络

```bash
docker network inspect yr-net
```


## 快速开始

### 1. 启动 Keycloak

**直连模式**（浏览器直接访问 Keycloak 端口）：

```bash
./start-keycloak.sh start
```

**反向代理模式**（浏览器通过 Traefik 访问，Keycloak 不直接暴露）：

```bash
KEYCLOAK_PUBLIC_URL=http://wyc.pc:18888 ./start-keycloak.sh start
```

> `KEYCLOAK_PUBLIC_URL` 告诉 Keycloak 自身的公开访问地址。如果不设置，Keycloak 会用内部地址（`localhost:8080`）构建 cookie domain 和 redirect，导致浏览器
> 收到 **"Cookie not found"** 错误。

等待 Keycloak 启动（约 30 秒），访问 http://localhost:8080 验证。

### 2. 初始化 Realm 和 Client

```bash
./init-realm.sh
```

这将创建：
- `yuanrong` realm
- `frontend` confidential client
- 测试用户和角色
- 开启自助注册（`registrationAllowed=true`）

### 3. 配置应用

根据 init-realm.sh 输出的配置，更新：

**frontend config.toml:**
```toml
[keycloakConfig]
url = "http://localhost:8080"
realm = "yuanrong"
clientId = "frontend"
clientSecret = "<从 init-realm.sh 输出获取>"
enabled = true
```

> 反向代理场景（如 Traefik）：`url` 设为公开地址供浏览器使用，同时设置 `internalUrl` 为 Keycloak 内部地址供服务端后端调用：
> ```toml
> [keycloakConfig]
> url = "http://wyc.pc:18888"      # 浏览器访问的公开地址
> internalUrl = "http://localhost:8080" # 服务端直连 Keycloak 的内部地址
> realm = "yuanrong"
> clientId = "frontend"
> clientSecret = "<从 init-realm.sh 输出获取>"
> enabled = true
> ```

**iam-server 启动参数:**
```
--keycloak_url=http://localhost:8080
--keycloak_realm=yuanrong
--keycloak_enabled=true
```

### 4. 测试认证流程

```bash
# 完整测试
./test-auth.sh all

# 仅测试 token 获取
./test-auth.sh token

# 测试 token 交换
./test-auth.sh exchange
```

## 测试用户

| 用户名 | 密码 | 角色 |
|--------|------|------|
| testuser | test123 | user |
| developer | dev123 | developer |
| testadmin | admin123 | admin |

> 说明：默认已开启 Keycloak 自助注册。你也可以通过前端 `/auth/register-page` 进入注册流程。

## 生产环境建议（关闭自助注册）

生产环境通常建议关闭自助注册，仅允许管理员创建账号：

```bash
REGISTRATION_ALLOWED=false ./init-realm.sh
```

如果你使用 `realm-export.json` 导入方式，也请确认：

```json
"registrationAllowed": false
```

这样前端注册入口仍可保留，但 Keycloak 不会允许匿名用户自助创建账号。

## 角色权限

| 角色 | 权限 |
|------|------|
| admin | 完全管理权限 |
| developer | 函数管理、日志查看 |
| user | 函数调用、日志查看 |
| viewer | 只读 |

## 管理命令

```bash
# 启动
./start-keycloak.sh start

# 停止
./start-keycloak.sh stop

# 重启
./start-keycloak.sh restart

# 状态
./start-keycloak.sh status
```

## 访问地址

- Keycloak: http://localhost:8080
- Admin Console: http://localhost:8080/admin
- Admin 凭据: admin / admin123

## 数据持久化

Keycloak 数据存储在 `./data/` 目录中。要重置：

```bash
./start-keycloak.sh stop
rm -rf ./data/
./start-keycloak.sh start
./init-realm.sh
```

## 与 Traefik 集成

当使用 Traefik 作为统一入口（frontend + Keycloak 共享同一端口）时：

### 配置说明

`example/traefik/dynamic.yml` 中 keycloak service 设置了 `passHostHeader: false`，
让 Traefik 用后端地址作为 Host 头转发给 Keycloak，避免 Host 不匹配导致的 cookie 问题。

### 启动顺序

```bash
# 1. 启动 Traefik（统一入口，默认监听 18888）
cd example/traefik
docker compose up -d

# 2. 启动 Keycloak，告知公开地址
cd example/keycloak
KEYCLOAK_PUBLIC_URL=http://wyc.pc:18888 ./start-keycloak.sh start

# 3. 初始化 realm
./init-realm.sh

# 4. 启动 frontend 运行时
# config.toml 中需配置：
#   url = "http://wyc.pc:18888"      （浏览器侧公开地址）
#   internalUrl = "http://localhost:8080" （服务端直连 Keycloak，避免经由外部 IP 绕回）
cd ../..
./example/restart.sh token
```

### 流量路由

```
浏览器 → wyc.pc:18888 (Traefik)
  ├── /realms/, /resources/, /js/ → Keycloak:8080
  └── /（其他）                   → frontend:8888
```

### 常见问题

**Cookie not found / We are sorry...**

Keycloak 在 HTTP（非 HTTPS）环境下，`AUTH_SESSION_ID` cookie 带有 `Secure; SameSite=None` 标志，浏览器拒绝存储，导致登录表单提交时 session 丢失。

解决方案：前端登录页 (`/auth/login-page`) 已改为**直接展示用户名/密码表单**，通过 password grant（`/auth/token/direct`）直接获取 IAM token，不再走 OAuth2 redirect/cookie 流程。

**注册按钮跳到了登录页**

旧版用 `kc_action=register` 触发注册，Keycloak 18+ 已废弃，正确 endpoint 为
`/realms/{realm}/protocol/openid-connect/registrations`，代码已更新。

---

## 故障排查

### Keycloak 启动失败

检查 Docker 是否运行：
```bash
docker ps
```

检查端口占用：
```bash
lsof -i :8080
```

### Token 获取失败

1. 确认 Keycloak 已启动
2. 确认 realm 和 client 已创建
3. 检查用户名密码是否正确

### Token 交换失败

1. 确认 iam-server 已启用 Keycloak 集成
2. 确认 iam-server 可以访问 Keycloak
3. 检查 iam-server 日志

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| KEYCLOAK_URL | http://localhost:8080 | Keycloak 内部监听地址 |
| KEYCLOAK_PUBLIC_URL | 同 KEYCLOAK_URL | Keycloak 公开访问地址（反向代理场景需设置）|

**frontend config.toml 字段说明：**

| 字段 | 说明 |
|------|------|
| `url` | Keycloak 公开访问地址，用于浏览器侧 OAuth2 跳转 |
| `internalUrl` | Keycloak 内部地址，用于服务端后端 token 请求（不设置则回退到 `url`）|
| KEYCLOAK_ADMIN | admin | 管理员用户名 |
| KEYCLOAK_ADMIN_PASSWORD | admin123 | 管理员密码 |
| CLIENT_SECRET | (随机生成) | Frontend client secret |
