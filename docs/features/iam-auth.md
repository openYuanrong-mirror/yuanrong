# IAM 认证与授权

## 概述

> **TODO**: 与函数系统对接调通，验证完整认证流程

集成 Keycloak 和 Casdoor 实现统一的身份认证与授权管理，支持配额同步轮询机制。

## 组件架构

    ┌─────────────┐     ┌─────────────┐
    │  Keycloak  │────▶│             │
    └─────────────┘     │   IAM       │
                        │   Server    │
    ┌─────────────┐     │             │
    │   Casdoor   │────▶│             │
    └─────────────┘     └─────────────┘
                              │
                              ▼
                        ┌─────────────┐
                        │  Frontend   │
                        └─────────────┘

## Keycloak 集成

### 认证流程

1. 用户访问 Frontend 登录页
2. 重定向至 Keycloak 登录
3. Keycloak 验证后返回 Authorization Code
4. Frontend 使用 Code 换取 Token
5. Token 用于后续 API 请求

### 接口说明

#### POST /iam-server/v1/token/login

Keycloak 登录接口（内部转发）

| 参数 | 类型 | 位置 | 说明 |
|------|------|------|------|
| username | string | body | 用户名 |
| password | string | body | 密码 |

#### POST /iam-server/v1/token/code-exchange

Token 交换接口（使用 Keycloak 授权码）

| 参数 | 类型 | 位置 | 说明 |
|------|------|------|------|
| code | string | body | Keycloak 授权码 |
| redirect_uri | string | body | 重定向 URI |

#### GET /iam-server/v1/token/userinfo

获取用户信息

获取用户信息

| 参数 | 类型 | 位置 | 说明 |
|------|------|------|------|
| Authorization | string | header | Bearer Token |

**响应**：

```json
{
  "user_id": "user-123",
  "username": "testuser",
  "roles": ["admin", "developer"]
}
```

## Casdoor 集成

Casdoor 与 Keycloak 形成双认证源架构，支持 OAuth2.0 协议。

### 配置参数

| 参数 | 环境变量 | 说明 |
|------|----------|------|
| CASDOOR_ENDPOINT | string | Casdoor 服务地址 |
| CASDOOR_CLIENT_ID | string | 应用 Client ID |
| CASDOOR_CLIENT_SECRET | string | 应用密钥 |
| CASDOOR_ORGANIZATION | string | 组织名称 |

## 配额同步轮询

IAM Server 定期从 Keycloak/Casdoor 同步用户配额信息。

### 轮询机制

- 轮询间隔：可配置（默认 60 秒）
- 同步内容：用户角色、权限、配额限制
- 错误处理：同步失败不影响现有认证

### 接口说明

#### GET /api/iam/quota

获取用户配额信息

**响应**：

```json
{
  "tenant_id": "tenant-abc",
  "max_instances": 100,
  "used_instances": 25,
  "quota_type": "standard"
}
```

## Sandbox 外部认证

Sandbox 组件支持通过 IAM Server 进行外部认证。

### 认证流程

1. Sandbox 向 Frontend 请求认证 Token
2. Frontend 验证用户身份并返回 Token
3. Sandbox 使用 Token 与 Function System 通信

### 接口说明

#### POST /iam-server/v1/token/exchange

Token 交换接口（Sandbox 外部认证使用）

#### POST /api/sandbox/register

注册 Sandbox 实例

| 参数 | 类型 | 位置 | 说明 |
|------|------|------|------|
| sandbox_id | string | body | Sandbox 唯一标识 |
| tenant_id | string | body | 租户 ID |
| token | string | body | 认证 Token |

#### POST /api/sandbox/token-exchange

Token 交换（外部认证 -> 内部 Token）

| 参数 | 类型 | 位置 | 说明 |
|------|------|------|------|
| external_token | string | body | 外部认证 Token |
| scope | string | body | Token 作用域 |

## JWT Token

### Token 结构

```json
{
  "header": {
    "alg": "HS256",
    "typ": "JWT"
  },
  "payload": {
    "sub": "user-123",
    "tenant_id": "tenant-abc",
    "roles": ["developer"],
    "exp": 1700000000,
    "iat": 1699990000
  }
}
```

### Token 生成

| 参数 | 环境变量 | 说明 |
|------|----------|------|
| JWT_SECRET | string | Token 签名密钥 |
| JWT_EXPIRATION | int | Token 过期时间（秒） |

### 角色说明

| 角色 | 权限 |
|------|------|
| admin | 所有操作 |
| developer | 函数管理、调用 |
| operator | 监控、查看 |
| viewer | 只读访问 |

## 配置说明

IAM 服务器地址通过 `yr start` 的前端配置传入。

### 配置方式

**方式 1: 通过 values.toml 配置**

编辑 `~/.config/yr/values.toml` 或指定配置文件：

```toml
[values.frontend]
iam_addr = "127.0.0.1:31112"  # IAM 服务器地址
enable_func_token_auth = true  # 是否启用函数 Token 认证
```

**方式 2: 通过环境变量配置**

```bash
export FRONTEND_CONFIG='{"iamConfig":{"addr":"127.0.0.1:31112","enableFuncTokenAuth":true}}'
yr start
```

**方式 3: 命令行覆盖**

```bash
yr start -s 'values.frontend.iam_addr="127.0.0.1:31112"'
```

### 配置参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `iam_addr` | string | IAM 服务器地址（host:port 格式） |
| `enable_func_token_auth` | bool | 是否启用函数 Token 认证 |
