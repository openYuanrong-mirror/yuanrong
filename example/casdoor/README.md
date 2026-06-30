# Casdoor 身份管理集成指南

本项目已采用 **Casdoor** 作为默认的身份认证提供者（Identity Provider），并通过 **Traefik** 进行统一路由。

## 1. 快速启动 (Docker)

在项目根目录下，使用以下命令启动 Casdoor：

```bash
source ./start_with_casdoor.sh
```

此脚本会启动容器并导出 `CASDOOR_PUBLIC_ENDPOINT=http://wyc.pc:18888` 等核心环境变量。

## 2. 自动化初始化配置

我们提供了一个全自动化脚本，用于创建组织、应用、自定义配额字段并设置默认值。

```bash
# 执行此脚本完成环境初始化
./example/casdoor/setup_quotas.sh
```

**该脚本执行的操作包括：**
*   创建组织：`openyuanrong.org`
*   创建应用：`yuanrong`
*   配置自定义字段：`cpu_quota` 和 `mem_quota`
*   **注册默认值**：新用户注册后自动获得 **100** 的资源配额。
*   **权限限制**：用户可以看到自己的配额，但只有 **admin** 可以修改。

## 3. 路由转发 (Traefik)

为了安全起见，Casdoor 不直接对公网暴露，所有流量通过 Traefik (`wyc.pc:18888`) 转发：

*   **Casdoor 路径**: `/login`, `/signup`, `/api/casdoor`, `/static`, 等。
*   **Frontend 路径**: `/` (根路径及其他)。

相关配置位于 `example/traefik/dynamic.yml`。

## 4. 常用管理脚本

| 脚本 | 描述 |
| :--- | :--- |
| `./example/casdoor/setup_quotas.sh` | 初始化组织、应用、配额字段和默认值。 |
| `./example/casdoor/clear_casdoor_data.sh` | **一键清空数据**：停止容器并物理删除数据库，恢复到纯净状态。 |

## 5. 环境变量参考 (iam-server)

启动 `iam-server` 时使用的核心环境变量：

| 变量名 | 描述 | 默认值 |
| :--- | :--- | :--- |
| `AUTH_PROVIDER` | 身份源类型 | `casdoor` |
| `CASDOOR_ENDPOINT` | 内部 API 地址 (Server-to-Server) | `http://localhost:8000` |
| `CASDOOR_PUBLIC_ENDPOINT` | **浏览器访问地址** | `http://wyc.pc:18888` |
| `CASDOOR_ORGANIZATION` | 组织名称 | `openyuanrong.org` |
| `CASDOOR_APPLICATION` | 应用名称 | `yuanrong` |
| `CASDOOR_JWT_PUBLIC_KEY` | JWT 验证公钥 (PEM 格式) | (从 Certs 页面获取) |

## 6. 验证流程
1. 访问 `http://wyc.pc:18888/signup` 注册新用户。
2. 注册后在个人中心查看 `CPU Quota (Standard)` 是否为 `100`。
3. `iam-server` 会自动从用户的 JWT Token 中解析出这些配额值。
