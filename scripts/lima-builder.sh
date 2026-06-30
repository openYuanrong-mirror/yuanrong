#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Lima ARM64 构建环境设置脚本
# 在 macOS Apple Silicon 上运行 ARM64 Linux 进行构建

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VM_NAME="${VM_NAME:-yuanrong-builder}"
LIMA_TEMPLATE="${LIMA_TEMPLATE:-template://ubuntu}"

echo "=== YuanRong ARM64 远程构建环境设置 ==="
echo "VM 名称: ${VM_NAME}"
echo "项目根目录: ${PROJECT_ROOT}"

# 检查 lima 是否安装
if ! command -v limactl &> /dev/null; then
    echo "错误: limactl 未安装"
    echo "请在 macOS 上执行: brew install lima"
    exit 1
fi

# 创建 Lima 配置文件
LIMA_CONFIG="${SCRIPT_DIR}/lima-config.yaml"
cat > "${LIMA_CONFIG}" << 'EOF'
# Lima 配置 for YuanRong 构建
vmType: "vz"
rosetta:
  enabled: false
arch: "aarch64"
images:
  - location: "https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-arm64.img"
    arch: "aarch64"
    digest: "sha256:a57dbe665974df0305e73f2e9dda27000c9eee76871241f7ee8d89eb2ccdfa81"
mounts:
  - location: "~"
    writable: false
  - location: "/tmp/lima"
    writable: true
ssh:
  localPort: 60022
  loadDotSSHPubKeys: true
  forwardAgent: true
env:
  BAZEL_VERSION: "6.0.0"
  GO_VERSION: "1.21"
containerd:
  system: false
  user: false
provision:
  - mode: system
    script: |
      #!/bin/bash
      set -eux -o pipefail
      apt-get update
      DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        git \
        wget \
        curl \
        ninja-build \
        python3 \
        python3-pip \
        python3-dev \
        python3-venv \
        golang-1.21 \
        openjdk-17-jdk \
        pkg-config \
        libssl-dev \
        libcurl4-openssl-dev \
        libboost-all-dev \
        protobuf-compiler \
        libprotobuf-dev \
        grpc-1.21 \
        libgrpc-dev \
        libgtest-dev \
        zlib1g-dev

      # 安装 Bazel
      wget -O /usr/local/bin/bazel \
        https://github.com/bazelbuild/bazel/releases/download/6.0.0/bazel-6.0.0-linux-arm64
      chmod +x /usr/local/bin/bazel

      # 配置 Go
      ln -sf /usr/lib/go-1.21/bin/go /usr/local/bin/go
      ln -sf /usr/lib/go-1.21/bin/gofmt /usr/local/bin/gofmt

      # 配置 Python
      update-alternatives --install /usr/bin/python python /usr/bin/python3 1

      echo "=== 构建环境安装完成 ==="
provisionMode: system
firmware:
  legacyBIOS: false
video:
  display: "none"
networks:
  - lima: shared
EOF

echo ""
echo "=== 步骤 1: 创建/启动 Lima VM ==="

# 检查 VM 是否已存在
if limactl list "${VM_NAME}" 2>/dev/null | grep -q "${VM_NAME}.*Running"; then
    echo "VM '${VM_NAME}' 已在运行"
elif limactl list "${VM_NAME}" 2>/dev/null | grep -q "${VM_NAME}"; then
    echo "启动现有 VM '${VM_NAME}'..."
    limactl start "${VM_NAME}"
else
    echo "创建新 VM '${VM_NAME}'..."
    limactl start --name="${VM_NAME}" "${LIMA_CONFIG}"
fi

echo ""
echo "=== 步骤 2: 获取 VM 连接信息 ==="

# 等待 VM 完全启动
echo "等待 VM 启动..."
sleep 5

# 获取 SSH 连接信息
SSH_PORT=$(limactl list "${VM_NAME}" --json 2>/dev/null | grep -o '"sshLocalPort":[0-9]*' | cut -d: -f2)
if [ -z "${SSH_PORT}" ]; then
    SSH_PORT=60022
fi
echo "SSH 端口: ${SSH_PORT}"

echo ""
echo "=== 步骤 3: 创建远程构建脚本 ==="

REMOTE_BUILD_SCRIPT="${SCRIPT_DIR}/remote-build-arm64.sh"
cat > "${REMOTE_BUILD_SCRIPT}" << EOF
#!/bin/bash
# 远程 ARM64 构建脚本
# 使用方法: bash scripts/remote-build-arm64.sh [target]

set -e

SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
VM_NAME="${VM_NAME}"
SSH_PORT="${SSH_PORT}"
PROJECT_ROOT="${PROJECT_ROOT}"

# 默认构建目标
BUILD_TARGET="\${1:-all}"

echo "=== YuanRong ARM64 远程构建 ==="
echo "目标: \${BUILD_TARGET}"
echo "VM: \${VM_NAME}"
echo "SSH 端口: \${SSH_PORT}"

# 检查 VM 是否运行
if ! limactl list "\${VM_NAME}" 2>/dev/null | grep -q "\${VM_NAME}.*Running"; then
    echo "错误: VM '\${VM_NAME}' 未运行"
    echo "请先运行: bash scripts/lima-builder.sh"
    exit 1
fi

# 在 VM 内的工作目录
REMOTE_WORK_DIR="/home/\${USER}.linux/yuanrong-build"

echo ""
echo "=== 步骤 1: 同步代码到 VM ==="

# 创建远程目录
limactl shell "\${VM_NAME}" -- mkdir -p "\${REMOTE_WORK_DIR}"

# 同步代码 (排除构建产物)
echo "正在同步代码..."
rsync -avz --delete \
    --exclude='build/' \
    --exclude='output/' \
    --exclude='bazel-*' \
    --exclude='.git' \
    --exclude='frontend/node_modules' \
    --exclude='datasystem/build' \
    --exclude='functionsystem/vendor' \
    --exclude='*.o' \
    --exclude='*.a' \
    --exclude='*.so' \
    "\${PROJECT_ROOT}/" \
    "lima-\${VM_NAME}:\${REMOTE_WORK_DIR}/"

echo "代码同步完成"

echo ""
echo "=== 步骤 2: 在 VM 中执行构建 ==="

# 在 VM 中执行构建
limactl shell "\${VM_NAME}" -- bash -c "
    cd \${REMOTE_WORK_DIR} && \\
    export BAZEL_OPTS=\\"--platforms=@local_config_platform//:host\\" && \\
    echo \\"=== ARM64 构建开始 ===\\" && \\
    make \${BUILD_TARGET} -j\$(nproc)
"

echo ""
echo "=== 步骤 3: 同步构建产物回本地 ==="

# 创建本地输出目录
mkdir -p "\${PROJECT_ROOT}/output"

# 同步产物
rsync -avz \\
    "lima-\${VM_NAME}:\${REMOTE_WORK_DIR}/output/" \\
    "\${PROJECT_ROOT}/output/"

echo ""
echo "=== ARM64 构建完成 ==="
echo "产物位置: \${PROJECT_ROOT}/output/"
ls -la "\${PROJECT_ROOT}/output/"
EOF

chmod +x "${REMOTE_BUILD_SCRIPT}"

echo ""
echo "=== 步骤 4: 创建快速构建别名 ==="

ALIAS_FILE="${SCRIPT_DIR}/build-aliases.sh"
cat > "${ALIAS_FILE}" << EOF
#!/bin/bash
# YuanRong ARM64 构建别名
# Source 此文件后可使用快捷命令

export YR_VM_NAME="${VM_NAME}"
export YR_SSH_PORT="${SSH_PORT}"
export YR_PROJECT_ROOT="${PROJECT_ROOT}"

# 快捷进入 VM
alias yr-vm="limactl shell \${YR_VM_NAME}"

# 快捷构建
alias yr-build="bash \${YR_PROJECT_ROOT}/scripts/remote-build-arm64.sh"
alias yr-build-all="bash \${YR_PROJECT_ROOT}/scripts/remote-build-arm64.sh all"
alias yr-build-fs="bash \${YR_PROJECT_ROOT}/scripts/remote-build-arm64.sh functionsystem"
alias yr-build-ds="bash \${YR_PROJECT_ROOT}/scripts/remote-build-arm64.sh datasystem"
alias yr-build-rt="bash \${YR_PROJECT_ROOT}/scripts/remote-build-arm64.sh yuanrong"

# 同步代码
alias yr-sync="rsync -avz --delete --exclude='build/' --exclude='output/' --exclude='bazel-*' \${YR_PROJECT_ROOT}/ lima-\${YR_VM_NAME}:/home/\${USER}.linux/yuanrong-build/"

# 查看构建产物
alias yr-ls="ls -la \${YR_PROJECT_ROOT}/output/"

echo "YuanRong ARM64 构建别名已加载"
echo "可用命令: yr-vm, yr-build, yr-build-all, yr-sync, yr-ls"
EOF

chmod +x "${ALIAS_FILE}"

echo ""
echo "=========================================="
echo "  Lima ARM64 构建环境设置完成!"
echo "=========================================="
echo ""
echo "使用方法:"
echo ""
echo "1. 首次使用 - 加载别名:"
echo "   source scripts/build-aliases.sh"
echo ""
echo "2. 快速构建:"
echo "   yr-build              # 构建默认目标"
echo "   yr-build-all          # 构建全部"
echo "   yr-build-fs           # 仅构建 functionsystem"
echo ""
echo "3. 进入 VM:"
echo "   yr-vm"
echo ""
echo "4. 直接使用构建脚本:"
echo "   bash scripts/remote-build-arm64.sh [target]"
echo ""
echo "=========================================="
