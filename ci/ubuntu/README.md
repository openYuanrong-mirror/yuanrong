# Ubuntu 20.04 多架构编译环境镜像

该目录包含用于从 Ubuntu 20.04 基础镜像构建编译环境镜像的 Dockerfile 和脚本，支持 **x86_64 (amd64)** 和 **ARM64 (aarch64)** 架构。

## 包含的工具
- **JDK 8** (Eclipse Temurin)
- **Maven 3.9.11**
- **Go 1.24.1**
- **Python** (3.9.11, 3.10.2, 3.11.4, 3.12.0, 3.13.0 - 均由源码构建)
- **Bazel 6.5.0**
- **CMake 3.31.10**
- **Protoc 25.1**
- **Node.js v20.19.0**
- **Ninja 1.12.0**
- **GCC 10 / G++ 10**

## 快速构建与推送

我们使用了 `docker buildx` 来实现一次性构建多架构镜像并自动合并 Manifest。

### 前提条件
1. 确保已安装 Docker Desktop (Mac/Windows) 或配置了 `binfmt` 的 Linux 环境。
2. 已登录华为云 SWR：
   ```bash
   docker login -u [区域项目名称]@[用户名] -p [密码] swr.cn-southwest-2.myhuaweicloud.com
   ```

### 构建步骤
直接运行目录下的构建脚本：
```bash
chmod +x build.sh
./build.sh
```

### 本地开发容器

如需本地启动一个通用开发容器：

```bash
cd ci/ubuntu
docker compose up -d
```

可选环境变量：

```bash
WORKSPACE=/path/to/yuanrong COMPILE_PORT=8888 docker compose up -d
```

## 为什么使用这种方式？
1. **统一管理**：通过 `ARG TARGETARCH` 变量，一个 Dockerfile 即可维护两套架构的下载和构建逻辑。
2. **自动合并**：`buildx` 会自动生成 Manifest List，用户执行 `docker pull` 时会根据其机器架构自动选择正确的镜像。
3. **兼容性**：脚本中显式关闭了 `--provenance` 和 `--sbom`，解决了华为云 SWR 不支持 OCI Attestations 导致的 `400 Bad Request` 问题。

## 手动构建单架构镜像（可选）
如果你只想在本地构建当前架构的镜像：
```bash
docker build -t compile-ubuntu2004:local -f Dockerfile.ubuntu2004 .
```
