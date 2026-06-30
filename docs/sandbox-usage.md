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
# 申请 token
yrcli token-require --iam-address <iam地址> --tenant-id <租户ID> --role admin

# 验证 token
yrcli token-auth --iam-address <iam地址> --token "<token>"

# 吊销 token
yrcli token-abandon --iam-address <iam地址> --token "<token>"
```
