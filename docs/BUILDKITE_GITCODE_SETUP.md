# Buildkite + GitCode 完整配置指南

本文档说明如何在 GitCode 上使用 Buildkite 进行 ARM64 构建。

## 架构

```text
GitCode 仓库
    ↓
Webhook 推送
    ↓
Buildkite 云端 (触发构建)
    ↓
Buildkite Agent (macOS 自托管)
    ↓
Docker 容器 (执行构建)
```

---

## 第一步：创建 Buildkite 组织

1. 访问 <https://buildkite.com>
2. 点击 "Sign up"
3. 使用邮箱注册（或用 GitHub 账号登录）
4. 创建组织，名称建议: `yuanrong` 或你的项目名

---

## 第二步：在 macOS 上设置 Agent

### 2.1 获取 Agent Token

```text
Buildkite Dashboard
  → Agents
  → New Agent
  → 选择: Generic
  → 复制 Agent Token
```

### 2.2 安装 Agent

在 macOS 上执行：

```bash
# 下载 Agent
curl -sL "https://raw.githubusercontent.com/buildkite/agent/main/install.sh" | bash -s

# 或者使用 Homebrew
brew install buildkite/buildkite/buildkite-agent
```

### 2.3 配置 Agent

```bash
# 编辑配置文件
vim ~/.buildkite-agent/buildkite-agent.cfg

# 添加以下内容
token="你的-agent-token"
name="macos-arm64-builder"
tags=os=macos,arch=arm64,docker=true
build-path=/var/buildkite-builds
hooks-path=/etc/buildkite-hooks
meta-data=os=macos,arch=arm64,docker=true
```

### 2.4 启动 Agent

```bash
# 方式1: 手动启动 (测试)
buildkite-agent start

# 方式2: 使用服务 (推荐)
brew services start buildkite/buildkite/buildkite-agent

# 检查状态
buildkite-agent status
```

### 2.5 验证 Agent

在 Buildkite Dashboard 查看：

```text
Agents → 应该能看到你的 macOS Agent 在线
```

---

## 第三步：创建 Pipeline

### 3.1 在 Buildkite 创建 Pipeline

```text
Buildkite Dashboard
  → Pipelines
  → New Pipeline
  → 选择: Generic
  → 填写:
      - Pipeline Name: yuanrong-build
      - Repository: https://gitcode.com/xxx/xxx.git
      - Branch: main 或 master
```

### 3.2 设置 Pipeline 为 Dynamic

在 Pipeline Settings 中：

```text
Settings → Steps → 选择: "Upload a pipeline script"
使用文件: .buildkite/pipeline.yml
```

---

## 第四步：配置 GitCode Webhook

### 4.1 获取 Webhook URL

```text
Buildkite Dashboard
  → 选择 Pipeline
  → Settings
  → Webhooks
  → 复制 Webhook URL (格式: https://webhook.buildkite.com/...)
```

### 4.2 在 GitCode 添加 Webhook

```text
GitCode 项目页面
  → 设置
  → Webhooks
  → 添加 Webhook
  → 填写:
      - URL: https://webhook.buildkite.com/...
      - Content Type: application/json
      - Secret: (留空或使用 Buildkite 提供的 secret)
      - 事件: Push events, Pull Request events
```

### 4.3 测试 Webhook

在 GitCode Webhook 设置中，点击 "测试推送"，Buildkite 应该能收到。

---

## 第五步：配置 Pipeline 文件

项目根目录创建 `.buildkite/pipeline.yml`：

```yaml
#.buildkite/pipeline.yml
env:
  BUILDER_IMAGE: "yuanrong/builder:arm64"
  BUILD_VERSION: "v0.0.1"
  JOBS: "4"
  GOPROXY: "https://goproxy.cn,direct"

steps:
  # 构建所有组件 (并行)
  - label: ":gopher: Frontend"
    command: "make frontend"
    agents:
      arch: "arm64"
      os: "macos"
    plugins:
      - docker-compose#v5.0.0:
          config: scripts/docker-compose.builder.yml
          run: builder
    retry:
      automatic:
        - limit: 1

  - label: ":database: DataSystem"
    command: "make datasystem"
    agents:
      arch: "arm64"
    plugins:
      - docker-compose#v5.0.0:
          config: scripts/docker-compose.builder.yml
          run: builder
    retry:
      automatic:
        - limit: 1

  - label: ":gear: FunctionSystem"
    command: "make functionsystem"
    agents:
      arch: "arm64"
    plugins:
      - docker-compose#v5.0.0:
          config: scripts/docker-compose.builder.yml
          run: builder
    retry:
      automatic:
        - limit: 1

  - label: ":package: Runtime"
    command: "make yuanrong"
    agents:
      arch: "arm64"
    plugins:
      - docker-compose#v5.0.0:
          config: scripts/docker-compose.builder.yml
          run: builder
    retry:
      automatic:
        - limit: 1

  # 等待构建完成
  - wait

  # 收集产物
  - label: ":floppy_disk: Artifacts"
    command: |
      #!/bin/bash
      echo "=== 构建产物 ==="
      ls -lah output/
    artifact_paths:
      - "output/**/*"
```

---

## 第六步：推送代码触发构建

```bash
git add .
git commit -m "Add Buildkite CI"
git push origin main
```

---

## 常见问题

### Q1: Agent 无法连接

检查 Agent 日志：

```bash
buildkite-agent start --debug
```

### Q2: Webhook 不触发

- 确认 Webhook URL 正确
- 在 Buildkite Dashboard → Activity Log 查看是否有记录
- 在 GitCode Webhook 设置中测试

### Q3: 构建失败

查看 Agent 日志：

```bash
tail -f ~/Library/Logs/buildkite-agent/buildkite-agent.log
```

---

## 附加：使用 Docker 运行 Agent

如果不想在 macOS 上直接安装 Agent，可以用 Docker：

```bash
# 创建配置文件
cat > buildkite-agent.env << EOF
BUILDKITE_AGENT_TOKEN=你的-token
BUILDKITE_AGENT_NAME=macos-arm64-docker
BUILDKITE_AGENT_TAGS=os=linux,arch=arm64,docker=true
EOF

# 运行 Agent 容器
docker run -d \
  --name buildkite-agent \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /tmp/buildkite-builds:/var/buildkite-builds \
  --env-file buildkite-agent.env \
  buildkite/agent:latest-arm64
```
