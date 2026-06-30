# Buildkite 华为云 OBS 配置指南

本文档说明如何将构建产物上传到华为云 OBS。

---

## 前置准备

### 1. 华为云 OBS 获取密钥

```text
华为云控制台
  → 对象存储服务 OBS
  → 创建桶 (Bucket)
  → 访问密钥 → 获取 Access Key ID 和 Secret Access Key
```

### 2. 记录以下信息

| 配置项 | 说明 | 示例 |
|--------|------|------|
| OBS_ENDPOINT | OBS 终端节点 | `obs.cn-north-4.myhuaweicloud.com` |
| OBS_BUCKET | 桶名称 | `yuanrong-builds` |
| OBS_ACCESS_KEY | 访问密钥 ID | `xxxxx` |
| OBS_SECRET_KEY | 访问密钥 | `xxxxx` |
| OBS_PATH_PREFIX | 存储路径前缀 | `yuanrong/builds` |

---

## 配置 Buildkite Pipeline

### 方式 1: Pipeline 环境变量 (推荐)

```text
Buildkite Dashboard
  → Pipeline Settings
  → Environment
  → 添加以下变量:
```

| 变量名 | 值 | 是否隐藏 |
|--------|-----|---------|
| `OBS_ENDPOINT` | `obs.cn-north-4.myhuaweicloud.com` | 否 |
| `OBS_BUCKET` | `your-bucket-name` | 否 |
| `OBS_ACCESS_KEY` | `your-access-key` | **是** ✅ |
| `OBS_SECRET_KEY` | `your-secret-key` | **是** ✅ |
| `OBS_PATH_PREFIX` | `yuanrong/builds` | 否 |

### 方式 2: 全局环境变量

```text
Buildkite Dashboard
  → Settings
  → Agents
  → Environment
  → 添加上述变量
```

---

## 华为云 OBS 区域对应 Endpoint

| 区域 | Endpoint |
|------|----------|
| 华北-北京四 | `obs.cn-north-4.myhuaweicloud.com` |
| 华南-广州 | `obs.cn-south-1.myhuaweicloud.com` |
| 华东-上海一 | `obs.cn-east-3.myhuaweicloud.com` |
| 华东-上海二 | `obs.cn-east-2.myhuaweicloud.com` |

---

## 产物命名规则

构建产物自动命名格式：

```text
yuanrong-{VERSION}-{PLATFORM}-{ARCH}-{COMMIT_SHORT}.tar.gz
```

示例：

```text
yuanrong-v0.0.1-linux-arm64-a1b2c3d4.tar.gz
yuanrong-v0.0.1-macos-arm64-a1b2c3d4.tar.gz
```

同时创建 `latest` 软链接：

```text
yuanrong-latest-linux-arm64.tar.gz
yuanrong-latest-macos-arm64.tar.gz
```

---

## OBS 存储结构

```text
your-bucket/
└── yuanrong/
    └── builds/
        ├── main/
        │   ├── 20260319-153045-a1b2c3d4/
        │   │   ├── yuanrong-v0.0.1-linux-arm64-a1b2c3d4.tar.gz
        │   │   ├── yuanrong-v0.0.1-macos-arm64-a1b2c3d4.tar.gz
        │   │   ├── yuanrong-latest-linux-arm64.tar.gz
        │   │   ├── yuanrong-latest-macos-arm64.tar.gz
        │   │   └── build-info-a1b2c3d4.json
        │   └── 20260319-160123-e5f6g7h8/
        │       └── ...
        └── develop/
            └── ...
```

---

## 下载产物

### 方式 1: 直接下载

```text
https://{bucket}.{endpoint}/{path}/{filename}

示例:
https://yuanrong-builds.obs.cn-north-4.myhuaweicloud.com/yuanrong/builds/main/20260319-153045-a1b2c3d4/yuanrong-v0.0.1-linux-arm64-a1b2c3d4.tar.gz
```

### 方式 2: obsutil 下载

```bash
# 安装 obsutil
wget https://obs-community.obs.cn-north-1.myhuaweicloud.com/obsutil/current/obsutil_linux_arm64.tar.gz
tar -xzvf obsutil_linux_arm64.tar.gz
./obsutil config -i

# 下载
./obsutil cp obs://yuanrong-builds/yuanrong/builds/main/20260319-153045-a1b2c3d4/yuanrong-v0.0.1-linux-arm64-a1b2c3d4.tar.gz ./
```

---

## 构建信息 JSON

每次构建会生成 `build-info-{commit}.json`：

```json
{
  "version": "v0.0.1",
  "commit": {
    "short": "a1b2c3d4",
    "full": "a1b2c3d4e5f6g7h8i9j0...",
    "message": "feat: add new feature",
    "branch": "main",
    "author": "Your Name"
  },
  "build": {
    "id": "123",
    "url": "https://buildkite.com/...",
    "agent": "macos-arm64-builder",
    "timestamp": "20260319-153045"
  },
  "artifacts": {
    "linux": "https://.../yuanrong-v0.0.1-linux-arm64-a1b2c3d4.tar.gz",
    "macos": "https://.../yuanrong-v0.0.1-macos-arm64-a1b2c3d4.tar.gz"
  }
}
```

---

## 故障排查

### 上传失败

1. **检查密钥是否正确**

   ```bash
   # 测试密钥
   aws s3 ls s3://your-bucket \
     --endpoint-url=https://obs.cn-north-4.myhuaweicloud.com \
     --region=auto
   ```

2. **检查桶是否存在**

   ```bash
   # 列出所有桶
   aws s3 ls \
     --endpoint-url=https://obs.cn-north-4.myhuaweicloud.com \
     --region=auto
   ```

3. **检查权限**
   - 确保 Access Key 有 OBS 操作权限
   - 桶策略允许上传

### 产物命名问题

产物名中的 `{BUILDKITE_COMMIT:0:8}` 是 shell 字符串截取，取 commit 的前 8 位。

如果需要完整 commit 或其他格式，修改 Pipeline 配置：

```bash
# 完整 commit (40 位)
COMMIT_FULL="${BUILDKITE_COMMIT}"

# 12 位
COMMIT_SHORT="${BUILDKITE_COMMIT:0:12}"

# 带分支名
COMMIT_WITH_BRANCH="${BUILDKITE_BRANCH}-${BUILDKITE_COMMIT:0:8}"
```
