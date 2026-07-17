# Sandbox 命令使用说明

## 前置条件

设置环境变量（仅需 2 个）：

```bash
export YR_SERVER_ADDRESS="114.116.246.103:8888"
export YR_JWT_TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjc3NzQzNTczNzgsInJvbGUiOiJkZXZlbG9wZXIiLCJzdWIiOiJkZWZhdWx0In0.OWFlZjU5MzQ2ZmU2NzFjNzJhYTk1YmY2M2M1ZDA1YzRlZWRmMDhiN2VlNjQxZWI0NGMzOTg2NGFjZWJmNGM1MQ"
```

SDK 会自动推断 `in_cluster=false`、`enable_tls=true`、`server_name`，无需手动设置。

## 命令一览

### 创建 Sandbox

```bash
yrcli sandbox create --namespace <命名空间> --name <名称>
```

```bash
yrcli sandbox create --namespace test --name mybox
# sandbox created, instance_name=test-mybox
```

默认配置：CPU 1000m、内存 2048MB、空闲超时 24 小时、lifecycle=detached。

### 列出 Sandbox

```bash
yrcli sandbox list                  # 列出所有
yrcli sandbox list --namespace test # 按命名空间过滤
```

### 查询 Sandbox 详情

```bash
yrcli sandbox query <sandbox-id>
```

### 删除 Sandbox

```bash
yrcli sandbox delete <sandbox-id>
```

```bash
yrcli sandbox delete test-mybox
# succeed to delete sandbox: test-mybox
```

### 远程执行命令

```bash
yrcli exec <sandbox-id> "<命令>"
```

```bash
yrcli exec test-mybox "ls /tmp"           # 执行单条命令
yrcli exec -i -t test-mybox "bash"        # 交互式终端
```

`-i` 分配 stdin，`-t` 分配 TTY，用于交互式会话。exec 通过 WebSocket 隧道连接到 sandbox 实例。

## Token 管理

```bash
# 通过 frontend 申请 developer token
yrcli token-require --frontend-address <frontend地址> --operator-token "<租户0 token>" --tenant-id <租户ID>

# 验证 token
yrcli token-auth --iam-address <iam地址> --token "<token>"

# 当前不支持通过 frontend abandon/revoke 已签发的 developer token。
# developer token 的失效依赖 token 自身 TTL。

# 集群内直连 iam-server 的运维入口
yrcluster token-require --iam-address <iam地址> --tenant-id <租户ID> --role developer
yrcluster token-abandon --iam-address <iam地址> --token "<token>" --tenant-id <租户ID>
```

`yrcli token-require` 是外部统一网关入口，只访问 frontend `/auth/token/require`，并要求 `--operator-token` 为租户 0 的 developer token。该流程不会写入 IdP，也不维护 email、quota 等 tenant profile。

## 多租户验收注意事项

- 创建和删除实例的端到端验收使用 SDK 链路，list 使用 `yrcli list instance`。
- SDK 创建 sandbox/长期运行实例时应显式指定完整函数 ID，例如 `sn:cn:yrk:default:function:0-defaultservice-py310:$latest`。
- `yrcli sandbox create` 保留兼容 fallback；当 SDK 返回 `invalid function` 或函数缺失类错误时，可能回退到 frontend sandbox API。多租户 RBAC 验收不应依赖该 fallback 判断 SDK create 行为。
- 租户 0 预期可查询和删除所有租户实例；普通 developer 租户只能查询和删除本租户实例。
