# IAM SSL 与 Frontend 路由配置指南

## 背景

IAM server 支持两种监听模式同时运行：

| 模式     | 地址                                   | 协议        | 用途                     |
|----------|----------------------------------------|-------------|--------------------------|
| 外部端口 | `{NODE_IP}:{IAM_SERVER_PORT}`          | TLS (mTLS)  | 跨 Pod / 远程访问        |
| 本地端口 | `127.0.0.1:{IAM_LOCAL_LISTEN_PORT}`    | 明文 TCP    | 同 Pod 内部访问，免证书  |

Frontend 访问 IAM 的地址选择逻辑：

- **同 Pod 部署**（`IAM_LOCAL_LISTEN_PORT != 0`）→ 自动使用本地回环地址，明文访问
- **跨 Pod 部署** → 使用外部地址，若开启了 TLS 则携带证书

---

## 配置参数说明

以下参数在 `deploy/process/config.sh` 中配置，也可通过启动脚本命令行传入：

```bash
# IAM server 端口（外部，默认 31112）
IAM_SERVER_PORT=31112

# IAM SSL 独立开关
# true  = IAM 单独开启 mTLS（即使全局 SSL_ENABLE=false 也生效）
# false = 跟随全局 SSL_ENABLE 配置
IAM_SSL_ENABLE="false"

# IAM 本地明文监听端口（同 Pod 访问用，0 = 禁用）
IAM_LOCAL_LISTEN_PORT="0"
# 必须是回环地址（127.x.x.x 或 ::1），默认 127.0.0.1
IAM_LOCAL_IP="127.0.0.1"

# 证书路径（IAM SSL 复用全局证书配置）
SSL_BASE_PATH="/etc/yuanrong/ssl"
SSL_ROOT_FILE="ca.crt"       # CA 根证书文件名
SSL_CERT_FILE="module.crt"   # 模块证书文件名
SSL_KEY_FILE="module.key"    # 模块私钥文件名
```

---

## 场景一：仅开启 IAM，全局不开 SSL

**需求**：整体部署不使用 SSL，但 IAM 对外端口需要 mTLS 保护。

### 场景一启动命令

```bash
bash deploy.sh \
  --enable_iam_server true \
  --iam_server_port 31112 \
  --iam_ssl_enable true \
  --ssl_base_path /etc/yuanrong/ssl \
  --ssl_root_file ca.crt \
  --ssl_cert_file module.crt \
  --ssl_key_file module.key \
  --ssl_enable false           # 全局其他组件不开 SSL
```

### 场景一效果

- IAM 外部端口 `{NODE_IP}:31112` 使用 mTLS
- 其他组件（function_proxy、function_master 等）明文通信
- 证书路径全部复用 `--ssl_base_path` 下的文件

---

## 场景二：Frontend 与 IAM 同 Pod 部署（推荐）

**需求**：Frontend 和 IAM 在同一个节点/Pod，Frontend 走本地回环访问 IAM 免证书，对外 IAM 仍开 mTLS。

### 场景二启动命令

```bash
# --iam_local_listen_port: 本地明文端口（不能与外部端口相同）
# --iam_local_ip:          默认 127.0.0.1，通常无需修改
bash deploy.sh \
  --enable_iam_server true \
  --enable_faas_frontend true \
  --iam_server_port 31112 \
  --iam_ssl_enable true \
  --ssl_base_path /etc/yuanrong/ssl \
  --ssl_root_file ca.crt \
  --ssl_cert_file module.crt \
  --ssl_key_file module.key \
  --iam_local_listen_port 31113 \
  --iam_local_ip 127.0.0.1
```

### 场景二架构

```text
同一个 Pod/Node:

┌─────────────────────────────────┐
│     Frontend (Go runtime)       │
│  ┌───────────────────────────┐  │
│  │ iamConfig.addr =          │  │
│  │ 127.0.0.1:31113           │  │
│  │ (自动选择，明文 TCP)      │  │
│  └───────────────────────────┘  │
│         │                        │
│         │ 本地回环              │
│         ▼                        │
│  ┌───────────────────────────┐  │
│  │  IAM Server               │  │
│  │  Port 31113 (明文)        │  │
│  │  Port 31112 (mTLS)◄──── 外部 │
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

### 场景二效果

IAM 同时监听两个端口：

- `{NODE_IP}:31112` → mTLS（对外，跨 Pod 访问）
- `127.0.0.1:31113` → 明文 TCP（对内，Frontend 访问）

Frontend 自动识别 `IAM_LOCAL_ADDRESS=127.0.0.1:31113`，**走明文回环，不需要配置证书**。

Frontend 配置文件中自动生成：

```json
"iamConfig": { "addr": "127.0.0.1:31113" },
"iamTlsConfig": { "sslEnable": false, ... }
```

### 场景二优势

- ✅ Frontend 和 IAM 通信零证书开销（本地回环）
- ✅ IAM 对外仍有 mTLS 保护
- ✅ 自动切换，无需手动配置

---

## 场景三：Frontend 与 IAM 分开部署（跨 Pod）

**需求**：IAM 和 Frontend 运行在不同节点/Pod，Frontend 需通过网络访问 IAM，使用证书验证。

### 场景三架构

```text
Pod A (IAM):                       Pod B (Frontend):

┌──────────────────┐             ┌─────────────────────────┐
│  IAM Server      │             │ Frontend (Go runtime)   │
│  Port 31112      │◄────mTLS────│ iamConfig.addr =        │
│  (mTLS)          │             │ 10.0.0.1:31112          │
│  10.0.0.1        │             │ (跨网络，TLS+证书)      │
└──────────────────┘             └─────────────────────────┘
```

### 场景三启动命令

**IAM 所在节点：**

```bash
# 场景三：IAM 节点不需要本地端口（Frontend 在另一节点通过 mTLS 访问）
bash deploy.sh \
  --enable_iam_server true \
  --iam_server_port 31112 \
  --iam_ssl_enable true \
  --ssl_base_path /etc/yuanrong/ssl \
  --ssl_root_file ca.crt \
  --ssl_cert_file module.crt \
  --ssl_key_file module.key
```

**Frontend 所在节点：**

```bash
# --iam_server_address: 对端 IAM 节点的 IP:Port
# --iam_ssl_enable:     通知 Frontend 需要以 TLS 连接 IAM
bash deploy.sh \
  --enable_faas_frontend true \
  --iam_server_address 10.0.0.1:31112 \
  --iam_ssl_enable true \
  --ssl_base_path /etc/yuanrong/ssl \
  --ssl_root_file ca.crt \
  --ssl_cert_file module.crt \
  --ssl_key_file module.key
```

### 场景三效果

Frontend 配置文件中自动生成：

```json
"iamConfig": { "addr": "10.0.0.1:31112" },
"iamTlsConfig": {
  "sslEnable": true,
  "caFile": "/etc/yuanrong/ssl/ca.crt",
  "certFile": "/etc/yuanrong/ssl/module.crt",
  "keyFile": "/etc/yuanrong/ssl/module.key"
}
```

Frontend 与 IAM 通信走网络 mTLS，带证书验证。

### 场景三注意事项

- 两边的证书文件必须一致（CA、cert、key 必须配对）
- 如果证书校验失败，Frontend 启动时会报 TLS 错误

---

## 参数优先级总结

### IAM SSL 开关优先级

```text
高优先级  ┬─→ --iam_ssl_enable true/false   （IAM 独立控制，本次新增）
          │
低优先级  └─→ --ssl_enable true/false       （全局控制，fallback）
```

**规则**：

- 如果 `--iam_ssl_enable` 显式设置（true/false），则使用该值
- 否则，跟随全局 `--ssl_enable` 配置

### Frontend IAM 地址选择逻辑

```text
1. 检查 IAM_LOCAL_LISTEN_PORT 是否设置且非 0
   ├─ YES → 使用 127.0.0.1:{IAM_LOCAL_LISTEN_PORT}（明文）
   └─ NO  → 使用 {IAM_SERVER_ADDRESS}
            ├─ IAM_SSL_ENABLE/SSL_ENABLE 开启 → TLS 模式
            └─ 否则 → 明文 HTTP
```

### 证书路径

- IAM server 和 Frontend **均复用**全局 `SSL_BASE_PATH/SSL_ROOT_FILE/SSL_CERT_FILE/SSL_KEY_FILE`
- 无单独的 IAM 专用证书路径参数

---

## 常见问题

### Q: `IAM_SSL_ENABLE=true` 但没有配置 `SSL_BASE_PATH` 会怎样？

**A:** `GetSSLCertConfig()` 检测证书文件不存在时会打印 `missing ssl cert files` 错误日志，
并以 `isEnable=false` 启动（回退为明文）。

> ⚠️ **生产环境警告**：这是 **fail-open** 行为——证书文件缺失或路径配置错误时，IAM
> 会在无感知的情况下以明文方式暴露服务。
>
> 建议在生产部署中：
>
> 1. 使用监控脚本检查证书文件是否存在（参考[部署清单](#部署清单)）
> 2. 在 IAM 启动后立即验证 TLS 连接是否真正生效（`openssl s_client` 测试）
> 3. 若运行在 Kubernetes，使用 InitContainer 预先校验证书，防止 fail-open 启动

### Q: 本地端口和外部端口可以相同吗？

**A:** 不能，必须使用不同端口。建议：

- 外部端口用 `31112`（主 IAM 服务端口）
- 本地端口用 `31113`（本地明文端口）

### Q: 如何验证 IAM 本地端口工作正常？

**A:** 在 Pod 内部运行：

```bash
curl -v http://127.0.0.1:31113/iam/v1/auth/token
```

应该收到 HTTP 401（缺少认证），而非 TLS 错误。

### Q: `X-Internal-Src` 头是什么？

**A:** IAM server 的本地明文端口收到的请求，**由服务端 http_iomgr 无条件剥除客户端传入
的同名头后**，仅为来自本地端口的连接重新注入 `X-Internal-Src: 1`。IAM 的 `RequestFilter`
识别后跳过 AKSK 签名校验，允许内部免认证访问。

**安全要点：**

- 该头**仅服务端注入**，客户端无法伪造——即使攻击者在外部 TLS 端口发送
  `X-Internal-Src: 1`，服务端也会在注入前先将其剥除，最终 RequestFilter 收到的值仍为 `0`。
- `X-Internal-Src` 有效的根本原因是**监听端口**（本地 vs 外部），而非请求头本身的内容。
- 该机制仅实现"同 Pod 内部免认证"，跨网络的请求始终经过 AKSK 或 TLS mTLS 校验。

### Q: 如何在运行时切换 IAM 地址（如 Pod 迁移）？

**A:** 修改环境变量并重启 Frontend：

```bash
# 更新 Frontend 配置
IAM_SERVER_ADDRESS="新IP:新Port" \
IAM_SSL_ENABLE="true/false" \
bash deploy.sh --enable_faas_frontend true ...
```

---

## 部署清单

部署前检查：

- [ ] 证书文件已放在 `SSL_BASE_PATH` 目录：
  - [ ] `ca.crt`（CA 根证书）
  - [ ] `module.crt`（模块证书）
  - [ ] `module.key`（模块私钥）
- [ ] `IAM_SERVER_PORT` 端口未被占用
- [ ] `IAM_LOCAL_LISTEN_PORT` 端口未被占用（同 Pod 时）
- [ ] 两个 Pod 间网络连通（跨 Pod 时）
- [ ] 防火墙规则允许 IAM 端口

---

## 相关源代码

**IAM flags（SSL 参数）：**

- `functionsystem/src/iam_server/flags/flags.h` — `GetIAMSslEnable()`, `HasIAMSslOverride()`
- `functionsystem/src/iam_server/flags/flags.cpp` — `iam_ssl_enable` flag 注册

**部署脚本：**

- `deploy/process/config.sh` — 配置项定义
- `deploy/process/deploy.sh` — `start_iam_server()` 逻辑，`IAM_LOCAL_ADDRESS` 导出
- `functionsystem/scripts/deploy/function_system/install.sh` — IAM 启动参数、Frontend 智能路由

**Frontend 配置：**

- `frontend/build/init_frontend_args.json` — `iamTlsConfig` 模板

**单元测试：**

- `functionsystem/tests/unit/iam_server/iam_dual_port_test.cpp` — 16 个测试（双端口 + SSL）
