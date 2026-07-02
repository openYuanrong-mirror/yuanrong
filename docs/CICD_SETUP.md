# YuanRong CI/CD 构建系统设置

本文档说明如何使用 CI/CD 工具搭建 ARM64 远程构建系统。

## 方案对比

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **Jenkins** | 功能强大，灵活，自托管 | 需要自己维护 | 企业级项目，复杂流程 |
| **GitHub Actions** | 简单易用，界面友好 | 有限的自托管 runner | 开源项目，小团队 |
| **GitLab CI** | 集成良好，内置 Docker | 需要 GitLab | 使用 GitLab 的团队 |
| **脚本直接调用** | 最简单，无依赖 | 无 UI，无历史 | 个人项目，快速验证 |

---

## 方案一: Jenkins

### 快速启动

```bash
# 1. 启动 Jenkins
bash scripts/setup-jenkins.sh start

# 2. 获取访问信息
bash scripts/setup-jenkins.sh url

# 3. 访问 http://localhost:8080 完成初始化
```

### 配置 macOS 构建节点

1. **在 macOS 上启用 Docker Remote API** (如果需要 TCP 连接):

```bash
# 编辑 Docker Desktop 配置
# Settings → Advanced → Expose daemon on tcp://localhost:2375 without TLS
```

1. **在 Jenkins 中添加节点**:

```text
Manage Jenkins → Manage Nodes and Clouds → New Node
├─ Name: macos-arm64
├─ Type: Permanent Agent
├─ Remote root directory: /home/jenkins/agent
├─ Launch method: Launch agents via SSH
│  ├─ Host: <macOS IP 地址>
│  ├─ Credentials: 添加 macOS SSH 凭据
│  └─ Host Key Verification Strategy: Non-verifying
└─ Availability: Keep this agent online as much as possible
```

1. **创建 Pipeline 任务**:

```text
New Item → Pipeline
├─ Name: yuanrong-arm64-build
├─ Pipeline script from SCM
│  ├─ SCM: Git
│  ├─ Repository URL: <你的仓库地址>
│  └─ Script Path: Jenkinsfile.v2
└─ Build Parameters
   ├─ String Parameter: BUILDER_IMAGE (默认: yuanrong/builder:arm64)
   ├─ Choice Parameter: BUILD_TARGET (all, frontend, datasystem...)
   └─ Boolean Parameter: USE_MACOS_BUILDER (默认: true)
```

### 使用

构建时选择参数，点击 "Build with Parameters" 即可。

---

## 方案二: GitHub Actions

### 设置自托管 Runner

在 macOS 上安装并注册 GitHub Actions Runner:

```bash
# 1. 下载 runner
# 访问: https://github.com/<org>/<repo>/settings/actions/runners/new

# 2. 解压并配置
mkdir actions-runner && cd actions-runner
curl -o actions-runner-osx-arm64-2.311.0.tar.gz -L https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-osx-arm64-2.311.0.tar.gz
tar xzf ./actions-runner-osx-arm64-2.311.0.tar.gz

# 3. 配置 (使用 GitHub 提供的 token)
./config.sh --url https://github.com/<org>/<repo> --token <token>

# 4. 安装并启动
./svc.sh install
./svc.sh start
```

### 触发构建

| 触发方式 | 说明 |
|----------|------|
| Push | 推送到 main/master/develop 分支 |
| Pull Request | 创建/更新 PR |
| Manual | workflow_dispatch - 手动触发，可选择构建目标 |

### 查看结果

访问: `https://github.com/<org>/<repo>/actions`

---

## 方案三: 脚本直接调用 (最简单)

无需 CI/CD 工具，直接使用构建脚本:

```bash
# 方式1: 本地执行 Docker 构建
bash scripts/docker-remote-build.sh build all

# 方式2: 通过 SSH 远程执行
ssh user@macos-host "cd /path/to/sandbox && make all"

# 方式3: 同步代码后远程构建
rsync -avz --exclude='output/' . user@macos-host:/tmp/build/
ssh user@macos-host "cd /tmp/build && make all"
rsync -avz user@macos-host:/tmp/build/output/ output/
```

---

## Docker 构建镜像

### 创建构建镜像

```bash
# 基于示例 Dockerfile
docker build -t yuanrong/builder:arm64 -f scripts/Dockerfile.builder.example .

# 推送到镜像仓库
docker push yuanrong/builder:arm64
```

### 镜像要求

| 组件 | 版本要求 |
|------|----------|
| Platform | linux/arm64 |
| Bazel | 6.0.0+ |
| CMake | 3.20+ |
| GCC/Clang | C++17 支持 |
| Go | 1.21+ |
| Python | 3.9+ |
| Java | OpenJDK 17+ |

---

## 常见问题

### Q: macOS Docker 连接失败

A: 确保开启了 Docker Remote API 或使用 SSH 方式连接

### Q: 构建速度慢

A: 检查并发数设置，考虑使用 Bazel 远程缓存

### Q: 产物不完整

A: 检查 volume mount 路径，确保 output 目录正确映射

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `Jenkinsfile.v2` | Jenkins Pipeline 定义 |
| `.github/workflows/build-arm64.yml` | GitHub Actions workflow |
| `scripts/docker-remote-build.sh` | Docker 构建脚本 |
| `scripts/setup-jenkins.sh` | Jenkins 快速设置脚本 |
| `scripts/docker-compose.jenkins.yml` | Jenkins Docker Compose 配置 |
| `scripts/Dockerfile.builder.example` | 构建镜像示例 |
