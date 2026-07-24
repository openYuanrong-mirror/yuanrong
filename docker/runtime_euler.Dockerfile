# ============================================
# 基于 openEuler 24.03 的 Yuanrong Python Runtime 镜像
# 支持 x86_64 (amd64) 和 aarch64 (arm64) 双架构
# 构建: DOCKER_BUILDKIT=1 docker build \
#   --build-arg YUANRONG_VERSION=9.9.9 \
#   --build-arg SDK_BASE_URL=https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/daily_build/202607222210/openeuler/x86_64/ \
#   -f runtime_euler.Dockerfile .
# ============================================

# 国内构建请通过 --build-arg BASE_IMAGE 指定加速源，例如:
#   --build-arg BASE_IMAGE=swr.cn-east-3.myhuaweicloud.com/kubesre/docker.io/openeuler/openeuler:24.03
# 或先 docker pull + docker tag 成 openeuler/openeuler:24.03
ARG BASE_IMAGE=openeuler/openeuler:24.03
FROM ${BASE_IMAGE}

# 设置语言环境
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# openEuler 24.03 自带 Python 3.11，无需源码编译
ARG PYTHON_MAJOR_MINOR=3.11

# 安装 Python 3.11 及运行时依赖（最小化）
# 注：tini 不在 openEuler 默认仓库中，信号处理和僵尸进程回收由
# DockerExecutor 创建容器时使用 --init 参数处理（Docker 自带 tini）
RUN dnf update -y && dnf install -y \
    python${PYTHON_MAJOR_MINOR} \
    python3-pip \
    ca-certificates \
    openssl-libs \
    sqlite-libs \
    readline \
    libffi \
    bzip2-libs \
    xz-libs \
    wget \
    tar \
    && dnf clean all

# 设置环境变量
ENV PATH="/usr/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 创建 python/pip 软链接
RUN ln -sf /usr/bin/python${PYTHON_MAJOR_MINOR} /usr/local/bin/python && \
    ln -sf /usr/bin/pip${PYTHON_MAJOR_MINOR} /usr/local/bin/pip

# 配置 pip 使用清华镜像源
RUN pip${PYTHON_MAJOR_MINOR} config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip${PYTHON_MAJOR_MINOR} config set global.timeout 100

# 验证 Python 版本
RUN python --version

# 下载并安装 openyuanrong_sdk
# 通过 --build-arg 传入版本号和 whl 包所在 URL（末尾需带 /）
# SDK_BASE_URL 中包含架构路径，例如:
#   x86_64:  https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/daily_build/202607222210/openeuler/x86_64/
#   aarch64: https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/daily_build/202607222210/openeuler/aarch64/
# 目标架构通过 uname -m 自动检测（交叉构建时 BuildKit 会模拟目标架构）:
#   x86_64  → whl 包名带 manylinux_2_34_x86_64
#   aarch64 → whl 包名带 manylinux_2_34_aarch64
# wheel 的 cpython tag（如 cp311）从 PYTHON_MAJOR_MINOR 动态派生，避免硬编码
ARG YUANRONG_VERSION=9.9.9
ARG SDK_BASE_URL

# 根据当前系统架构自动选择对应 wheel 包下载
# 注：保存为原始 wheel 文件名，pip 通过文件名解析 wheel 元数据，
# 改名会导致 "is not a valid wheel filename" 错误
RUN if [ -z "$SDK_BASE_URL" ]; then \
        echo "ERROR: SDK_BASE_URL build-arg is required (must end with /)" >&2; \
        exit 1; \
    fi && \
    ARCH=$(uname -m) && \
    CP_TAG="cp${PYTHON_MAJOR_MINOR/./}" && \
    WHEEL_NAME="openyuanrong_sdk-${YUANRONG_VERSION}-${CP_TAG}-${CP_TAG}-manylinux_2_34_${ARCH}.whl" && \
    DOWNLOAD_URL="${SDK_BASE_URL}${WHEEL_NAME}" && \
    echo "Downloading: $DOWNLOAD_URL" && \
    wget --timeout=60 --tries=3 "$DOWNLOAD_URL" -P /tmp/ && \
    pip install --no-cache-dir "/tmp/${WHEEL_NAME}" && \
    rm -f "/tmp/${WHEEL_NAME}"

# 验证安装（不使用 || true，安装失败应立即中断构建）
RUN python -c "import sys; print(f'Python version: {sys.version}')" && \
    pip list | grep openyuanrong