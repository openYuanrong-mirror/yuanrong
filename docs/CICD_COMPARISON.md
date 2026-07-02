# YuanRong CI/CD 方案对比

本文档对比各种 CI/CD 方案，帮助你选择最合适的构建系统。

## 方案总览

| 方案 | 自托管难度 | 界面友好度 | 功能完整度 | 推荐场景 |
|------|-----------|----------|-----------|---------|
| **Buildkite** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 强烈推荐 |
| **GitHub Actions** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | GitHub 项目首选 |
| **Jenkins** | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 复杂企业流程 |
| **GitLab CI** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | GitLab 用户 |
| **CircleCI** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | 简单项目 |
| **Woodpecker** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | 轻量自托管 |
| **脚本** | ⭐ | ⭐ | ⭐⭐ | 快速验证 |

---

## 推荐方案详解

### 1. Buildkite ⭐⭐⭐⭐⭐ 强烈推荐

**为什么推荐 Buildkite:**

- ✅ **专为自托管设计**: 控制平面托管，构建节点完全自托管
- ✅ **原生 Docker 支持**: 每个步骤独立容器
- ✅ **动态 Pipeline**: 用脚本生成构建步骤，极其灵活
- ✅ **macOS 友好**: 完美支持 macOS 构建节点
- ✅ **界面美观**: 实时日志输出，构建状态一目了然

**架构:**

```text
Buildkite 云端 (控制平面)
    ↓
API/Webhook
    ↓
macOS 自托管 Agent (构建节点)
    ↓
Docker 容器 (隔离构建环境)
```

**快速开始:**

```bash
# 1. 在 macOS 上安装 Agent
export BUILDKITE_AGENT_TOKEN=your-token
bash scripts/setup-buildkite.sh setup
bash scripts/setup-buildkite.sh start

# 2. 在 Buildkite 创建 Pipeline
# 指向 .buildkite/pipeline.yml

# 3. 推送代码触发构建
git push
```

**配置文件示例:**

```yaml
# .buildkite/pipeline.yml
steps:
  - label: ":mac: ARM64 Build"
    command: "make all"
    agents:
      arch: "arm64"
    plugins:
      - docker-compose#v5.0.0:
          config: scripts/docker-compose.builder.yml
```

**定价:**

- 免费: 3 个并发构建
- 付费: 按使用量计费

---

### 2. GitHub Actions ⭐⭐⭐⭐ GitHub 项目首选

**优点:**

- ✅ 与 GitHub 深度集成
- ✅ 免费额度大 (公开项目无限，私有 2000 分钟/月)
- ✅ 界面友好，易于使用

**缺点:**

- ❌ 自托管 runner 需要自己维护
- ❌ 功能相对简单

**适用:**

- 开源项目
- 已使用 GitHub 的团队

**配置文件:**

```yaml
# .github/workflows/build.yml
name: ARM64 Build
on: [push, pull_request]
jobs:
  build:
    runs-on: [self-hosted, macos, arm64]
    steps:
      - uses: actions/checkout@v4
      - run: make all
```

---

### 3. Jenkins ⭐⭐⭐ 企业级复杂流程

**优点:**

- ✅ 功能最强大
- ✅ 插件生态丰富
- ✅ 完全免费开源

**缺点:**

- ❌ 配置复杂
- ❌ 维护成本高
- ❌ UI 较老旧

**适用:**

- 大型企业
- 复杂的构建流程
- 需要深度定制

---

### 4. GitLab CI ⭐⭐⭐⭐ GitLab 用户

**优点:**

- ✅ GitLab 内置集成
- ✅ 配置简单 (YAML)
- ✅ Docker 原生支持

**缺点:**

- ❌ 需要 GitLab

**配置文件:**

```yaml
# .gitlab-ci.yml
build-arm64:
  tags: [macos, arm64]
  image: yuanrong/builder:arm64
  script:
    - make all
  artifacts:
    paths:
      - output/
```

---

### 5. Woodpecker CI ⭐⭐⭐ 轻量自托管

**优点:**

- ✅ 完全开源免费
- ✅ 轻量级
- ✅ 界面简洁
- ✅ Fork 自 Drone CI

**缺点:**

- ❌ 功能相对简单
- ❌ 社区较小

**适用:**

- 完全自托管需求
- 预算有限

---

### 6. CircleCI ⭐⭐⭐ 简单项目

**优点:**

- ✅ 配置简单
- ✅ 速度快

**缺点:**

- ❌ 自托管需要付费
- ❌ macOS 构建需要付费

---

## 决策树

```text
开始
  │
  ├─ 已在使用 GitHub?
  │   └─ 是 → GitHub Actions
  │   └─ 否
  │
  ├─ 需要 macOS 构建节点?
  │   └─ 是 → Buildkite ⭐
  │   └─ 否
  │
  ├─ 预算有限?
  │   └─ 是 → Woodpecker 或 脚本
  │   └─ 否
  │
  ├─ 需要复杂流程/深度定制?
  │   └─ 是 → Jenkins
  │   └─ 否
  │
  └─ 默认推荐 → Buildkite
```

---

## 快速决策表

| 需求 | 推荐方案 |
|------|---------|
| 我要用 GitHub | GitHub Actions |
| 我要用 GitLab | GitLab CI |
| 我要 macOS ARM64 构建 | Buildkite |
| 我要完全免费自托管 | Woodpecker |
| 我要企业级功能 | Jenkins |
| 我要最快上手 | CircleCI 或 GitHub Actions |
| 我要最灵活 | Buildkite |

---

## 对比表

| 特性 | Buildkite | GitHub Actions | Jenkins | GitLab CI | Woodpecker |
|------|-----------|----------------|---------|-----------|-----------|
| **自托管** | ✅ 优秀 | ✅ 支持 | ✅ 支持 | ✅ 支持 | ✅ 优秀 |
| **macOS 支持** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| **动态 Pipeline** | ✅ | ⚠️ 复杂 | ✅ | ✅ | ✅ |
| **Docker 原生** | ✅ | ✅ | ⚠️ 需插件 | ✅ | ✅ |
| **免费额度** | 3 并发 | 2000 分钟 | 无限 | 无限 | 无限 |
| **易用性** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **学习曲线** | 低 | 低 | 高 | 中 | 低 |
| **UI 现代化** | ✅ | ✅ | ⚠️ | ✅ | ✅ |
| **API 质量** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |

---

## 总结

**强烈推荐 Buildkite**，因为:

1. 专为自托管设计，控制平面托管省心
2. 原生支持 macOS 构建节点
3. 动态 Pipeline 非常灵活
4. 界面美观，使用体验好

**如果已用 GitHub**，直接用 GitHub Actions 最省事。

**如果需要企业级功能**，选 Jenkins。

**如果预算有限**，选 Woodpecker 或直接脚本。

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `.buildkite/pipeline.yml` | Buildkite Pipeline 配置 |
| `.buildkite/pipeline.dynamic.yml` | 动态 Pipeline (脚本生成) |
| `scripts/setup-buildkite.sh` | Buildkite Agent 设置脚本 |
| `scripts/docker-compose.buildkite-agent.yml` | Agent Docker Compose 配置 |
| `scripts/setup-jenkins.sh` | Jenkins 设置脚本 |
| `.github/workflows/build-arm64.yml` | GitHub Actions 配置 |
| `Jenkinsfile.v2` | Jenkins Pipeline 配置 |
