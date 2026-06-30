# yrcli 命令行工具

## 概述

`yrcli` 是 YuanRong 的 Python 命令行工具，提供函数部署、调用、管理等能力。

## 全局选项

| 选项 | 环境变量 | 说明 |
|------|----------|------|
| `--server-address` | `YR_SERVER_ADDRESS` | YuanRong Server 地址 |
| `--ds-address` | `YR_DS_ADDRESS` | DataSystem 地址 |
| `--client-cert` | `YR_CERT_FILE` | 客户端证书路径 |
| `--client-key` | `YR_PRIVATE_KEY_FILE` | 客户端私钥路径 |
| `--ca-cert` | `YR_VERIFY_FILE` | CA 证书路径 |
| `--insecure` | `YR_INSECURE` | 跳过 TLS 验证 |
| `--client-auth-type` | `YR_CLIENT_AUTH_TYPE` | TLS 认证类型 (`mutual`\|`one-way`) |
| `--jwt-token` | `YR_JWT_TOKEN` | JWT 认证 Token |
| `--user` | - | 租户 ID（默认 `default`） |
| `--log-level` | - | 日志级别（默认 `INFO`） |

## 函数管理

### deploy - 部署函数

```bash
yrcli deploy [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `--backend` | 存储后端 (`ds`，默认 `ds`) |
| `--code-path` | 代码路径（默认 `.`） |
| `--format` | 打包格式 (`zip`\|`img`，默认 `zip`) |
| `--function-json` | 函数配置文件路径 |
| `--skip-package` | 跳过打包步骤 |
| `--update` | 更新已存在的函数 |
| `-r, --requirements` | requirements.txt 路径 |

**示例**：

```bash
# 部署函数
yrcli deploy --function-json my_function.json

# 带依赖部署
yrcli deploy --function-json my_function.json -r requirements.txt

# 更新函数
yrcli deploy --function-json my_function.json --update
```

### delete - 删除函数

```bash
yrcli delete -f <function-name> [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `-f, --function-name` | 函数名（必需） |
| `--no-clear-package` | 不删除代码包 |
| `-v, --version` | 版本（默认 `latest`） |

**示例**：

```bash
yrcli delete -f myservice@myfunction
yrcli delete -f myservice@myfunction -v 1.0.0
```

### query - 查询函数/实例

```bash
yrcli query [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `-f, --function-name` | 函数名 |
| `-i, --instance-id` | 实例 ID |

**示例**：

```bash
# 查询函数
yrcli query -f myservice@myfunction:latest

# 查询实例
yrcli query -i db6126e0-0000-4000-8000-00faf8d1692b
```

### list - 列出资源

```bash
yrcli list [resource_type]
```

**示例**：

```bash
# 列出函数
yrcli list
yrcli list function

# 列出实例
yrcli list instance
```

### publish - 发布函数版本

```bash
yrcli publish -f <function-name> [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `-f, --function-name` | 函数名（必需） |
| `-v, --version` | 版本号 |

**示例**：

```bash
yrcli publish -f myservice@myfunction:latest
```

## 函数调用

### invoke - 调用函数

```bash
yrcli invoke -f <function-name> [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `-f, --function-name` | 函数名（必需） |
| `--payload` | 请求 payload（JSON 字符串） |
| `--timeout` | 超时时间（秒，默认 30） |
| `--header` | 自定义请求头（格式 `Key:Value`） |
| `--async` | 异步调用模式 |

**示例**：

```bash
# 同步调用
yrcli invoke -f myservice@myfunction --payload '{"key": "value"}'
yrcli invoke -f myservice@myfunction --payload '{"data": "test"}' --timeout 60
yrcli invoke -f myservice@myfunction --header "X-Custom-Header:value"

# 异步调用
yrcli invoke -f myservice@myfunction --payload '{"data": "test"}' --async
```

### result - 查询异步调用结果

```bash
yrcli result <request_id>
```

**示例**：

```bash
yrcli result req-abc-123
```

## 数据管理

### clear - 清除代码包

```bash
yrcli clear <package>
```

**示例**：

```bash
yrcli clear ds://code-abc123.img
```

### download - 下载代码包

```bash
yrcli download <package>
```

**示例**：

```bash
yrcli download ds://code-abc123.img
```

## Sandbox 管理

### sandbox create - 创建 Sandbox 实例

```bash
yrcli sandbox create --namespace <ns> --name <name>
```

| 选项 | 说明 |
|------|------|
| `--namespace` | 命名空间（必需） |
| `--name` | 实例名称（必需） |

**示例**：

```bash
yrcli sandbox create --namespace myns --name mysandbox
```

### sandbox list - 列出 Sandbox 实例

```bash
yrcli sandbox list [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `--namespace` | 按命名空间过滤 |

**示例**：

```bash
yrcli sandbox list
yrcli sandbox list --namespace myns
```

### sandbox query - 查询 Sandbox 实例

```bash
yrcli sandbox query <sandbox_id>
```

**示例**：

```bash
yrcli sandbox query myns-mysandbox
```

### sandbox delete - 删除 Sandbox 实例

```bash
yrcli sandbox delete <sandbox_id>
```

**示例**：

```bash
yrcli sandbox delete myns-mysandbox
```

## 运行时部署

### deploy-language-rt - 部署语言运行时

```bash
yrcli deploy-language-rt [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `--runtime` | 运行时版本 (`python3.9`\|`python3.10`\|`python3.11`\|`python3.12`\|`python3.13`) |
| `--sdk` | 部署为 SDK 运行时 |
| `--no-rootfs` | 不使用 rootfs |
| `--function-json` | 函数配置文件路径 |

**示例**：

```bash
# 部署 Python 3.11 运行时
yrcli deploy-language-rt --runtime python3.11

# 部署 Python SDK 运行时
yrcli deploy-language-rt --runtime python3.11 --sdk

# 部署并自定义资源配置
yrcli deploy-language-rt --runtime python3.11 --cpu=1000 --memory=1024
```

## Token 管理

### token-auth - 验证 Token

```bash
yrcli token-auth --token <token> --iam-address <addr>
```

**示例**：

```bash
yrcli token-auth --iam-address 127.0.0.1:31112 --token "eyJhbGciOi..."
```

### token-require - 生成 Token

```bash
yrcli token-require --iam-address <addr> [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `--tenant-id` | 租户 ID |
| `--ttl` | Token 有效期（秒） |
| `--role` | Token 角色 |

**示例**：

```bash
yrcli token-require --iam-address 127.0.0.1:31112 --tenant-id tenant_789 --role viewer
yrcli token-require --iam-address 127.0.0.1:31112 --tenant-id user --ttl 3600 --role admin
```

### token-abandon - 撤销 Token

```bash
yrcli token-abandon --token <token> --iam-address <addr> [OPTIONS]
```

**示例**：

```bash
yrcli token-abandon --iam-address 127.0.0.1:31112 --token "eyJhbGciOi..."
```

## 实例执行

### exec - 在实例中执行命令

```bash
yrcli exec [OPTIONS] <instance> <command>
```

| 选项 | 说明 |
|------|------|
| `-i, --stdin` | 分配 stdin |
| `-t, --tty` | 分配 TTY |
| `--verify-server` | 验证服务器证书（默认 True） |

**示例**：

```bash
yrcli exec -i -t my-instance-123 "ls -la"
yrcli exec my-instance-123 "cat /proc/self/status"
```

## Spark 作业

### run-spark - 运行 Spark 作业

```bash
yrcli run-spark --script <script_path> [OPTIONS]
```

| 选项 | 说明 |
|------|------|
| `--script` | Python 脚本路径（必需） |
| `--args` | Spark 作业参数 |

**示例**：

```bash
yrcli run-spark --script /path/to/spark_script.py
yrcli run-spark --script /path/to/spark_script.py --args "arg1 arg2 arg3"
```

## 其他命令

### help - 显示帮助

```bash
yrcli help [command-name]
```

**示例**：

```bash
yrcli help
yrcli help deploy
yrcli help token-auth
```

### runtime_main - 启动运行时主进程

```bash
yrcli runtime_main
```

启动 YuanRong runtime 主进程。
