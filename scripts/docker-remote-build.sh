#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Docker 远程 ARM64 构建脚本
# 在 macOS 上通过 Docker 容器执行 ARM64 构建

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ========== 配置区域 ==========
# 请根据你的实际情况修改以下配置

# Docker 构建镜像名称
BUILD_IMAGE="${BUILD_IMAGE:-yuanrong/builder:arm64}"

# Docker 容器名称前缀
CONTAINER_NAME_PREFIX="yr-builder"

# macOS SSH 端口 (如果需要从远程访问)
MAC_SSH_PORT="${MAC_SSH_PORT:-2222}"

# 构建产物输出目录
OUTPUT_DIR="${PROJECT_ROOT}/output"

# ===============================

print_usage() {
    cat << EOF
使用方法: bash $0 [command] [target]

命令:
  setup     - 设置构建环境 (拉取镜像等)
  build     - 执行构建 (默认)
  shell     - 进入构建容器 shell
  clean     - 清理构建容器
  exec      - 在容器中执行自定义命令

构建目标 (与 make all 相同):
  all              - 构建所有组件 (默认)
  frontend         - 仅构建 frontend
  datasystem       - 仅构建 datasystem
  functionsystem   - 仅构建 functionsystem
  runtime_launcher - 仅构建 runtime_launcher
  dashboard        - 仅构建 dashboard
  yuanrong         - 仅构建 yuanrong

环境变量:
  BUILD_IMAGE      - 指定构建镜像 (默认: yuanrong/builder:arm64)
  MAC_SSH_PORT     - SSH 端口 (默认: 2222)

示例:
  # 首次使用 - 设置环境
  $0 setup

  # 构建所有组件
  $0 build all

  # 只构建 functionsystem
  $0 build functionsystem

  # 进入容器调试
  $0 shell

  # 清理容器
  $0 clean
EOF
}

# 检查 Docker 是否可用
check_docker() {
    if ! command -v docker &> /dev/null; then
        echo "错误: Docker 未安装"
        echo "请在 macOS 上安装 Docker Desktop: https://www.docker.com/products/docker-desktop"
        exit 1
    fi

    # 检查 Docker 是否运行
    if ! docker info &> /dev/null; then
        echo "错误: Docker 未运行，请启动 Docker Desktop"
        exit 1
    fi

    echo "✓ Docker 可用"
}

# 获取容器名称
get_container_name() {
    echo "${CONTAINER_NAME_PREFIX}-$$"
}

# 检查镜像是否存在
check_image() {
    if docker image inspect "${BUILD_IMAGE}" &> /dev/null; then
        echo "✓ 构建镜像存在: ${BUILD_IMAGE}"
        return 0
    else
        echo "✗ 构建镜像不存在: ${BUILD_IMAGE}"
        return 1
    fi
}

# 设置构建环境
cmd_setup() {
    echo "=== Docker ARM64 构建环境设置 ==="
    echo ""

    check_docker

    echo ""
    echo "检查构建镜像..."
    if check_image; then
        echo "镜像已存在，跳过拉取"
        echo "如需更新镜像，请执行: docker pull ${BUILD_IMAGE}"
    else
        echo "正在拉取构建镜像..."
        echo "镜像: ${BUILD_IMAGE}"
        echo ""
        echo "如果镜像不存在，请先构建或推送镜像:"
        echo "  docker build -t ${BUILD_IMAGE} -f path/to/Dockerfile ."
        echo "  # 或从 registry 拉取"
        echo "  docker pull ${BUILD_IMAGE}"
        echo ""
        read -p "按回车继续，或 Ctrl+C 退出..."
    fi

    # 创建输出目录
    mkdir -p "${OUTPUT_DIR}"

    echo ""
    echo "=== 设置完成 ==="
    echo "构建镜像: ${BUILD_IMAGE}"
    echo "项目目录: ${PROJECT_ROOT}"
    echo "输出目录: ${OUTPUT_DIR}"
    echo ""
    echo "现在可以运行: $0 build [target]"
}

# 运行构建容器
run_build_container() {
    local target="${1:-all}"
    local container_name=$(get_container_name)
    local workspace="/workspace"

    echo "=== Docker ARM64 构建 ==="
    echo "目标: ${target}"
    echo "镜像: ${BUILD_IMAGE}"
    echo "容器: ${container_name}"
    echo ""

    # Docker 运行选项
    local docker_opts=(
        --rm                          # 构建后删除容器
        --name "${container_name}"
        --platform linux/arm64        # ARM64 平台
        -v "${PROJECT_ROOT}:${workspace}"  # 挂载源代码
        -w "${workspace}"              # 工作目录
        -e "BUILD_VERSION=${BUILD_VERSION:-v0.0.1}"
        -e "JOBS=${JOBS:-$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)}"
        -e "GO111MODULE=on"
        -e "CGO_ENABLED=1"
        -e "GOOS=linux"
        -e "GOARCH=arm64"
    )

    # 如果有 GOPROXY，传递进去
    if [ -n "${GOPROXY}" ]; then
        docker_opts+=(-e "GOPROXY=${GOPROXY}")
    fi

    echo "开始构建..."
    echo "docker run ${docker_opts[*]} ${BUILD_IMAGE} make ${target}"
    echo ""

    # 运行构建
    docker run "${docker_opts[@]}" "${BUILD_IMAGE}" \
        bash -c "
            echo '=== 容器信息 ==='
            uname -a
            echo 'CPU: '\$(nproc) cores
            echo ''
            echo '=== 开始构建 ${target} ==='
            make ${target} -j\${JOBS}
        "

    echo ""
    echo "=== 构建完成 ==="
    echo "产物位置: ${OUTPUT_DIR}/"
    ls -la "${OUTPUT_DIR}/" 2>/dev/null || echo "暂无输出文件"
}

# 进入容器 shell
cmd_shell() {
    local container_name="${CONTAINER_NAME_PREFIX}-shell"
    local workspace="/workspace"

    echo "=== 进入构建容器 Shell ==="
    echo "输入 'exit' 退出"
    echo ""

    # 检查是否已有 shell 容器在运行
    if docker ps --filter "name=${container_name}" --format '{{.Names}}' | grep -q "^${container_name}$"; then
        echo "已存在运行中的容器，正在连接..."
        docker exec -it "${container_name}" bash
    else
        echo "启动新容器..."
        docker run -it --rm \
            --name "${container_name}" \
            --platform linux/arm64 \
            -v "${PROJECT_ROOT}:${workspace}" \
            -w "${workspace}" \
            -e "GO111MODULE=on" \
            -e "GOPROXY=${GOPROXY:-https://goproxy.cn,direct}" \
            "${BUILD_IMAGE}" \
            bash
    fi
}

# 清理容器
cmd_clean() {
    echo "=== 清理构建容器 ==="
    echo ""

    # 停止并删除所有相关容器
    local containers=$(docker ps -a --filter "name=${CONTAINER_NAME_PREFIX}" --format '{{.Names}}')
    if [ -n "$containers" ]; then
        echo "删除容器:"
        echo "$containers"
        echo "$containers" | xargs docker rm -f
    else
        echo "没有需要清理的容器"
    fi

    echo ""
    echo "=== 清理完成 ==="
}

# 在容器中执行自定义命令
cmd_exec() {
    shift  # 移除 'exec' 参数
    if [ $# -eq 0 ]; then
        echo "错误: 请指定要执行的命令"
        echo "示例: $0 exec bash -c 'pwd && ls'"
        exit 1
    fi

    local workspace="/workspace"

    docker run --rm -it \
        --platform linux/arm64 \
        -v "${PROJECT_ROOT}:${workspace}" \
        -w "${workspace}" \
        "${BUILD_IMAGE}" \
        "$@"
}

# ========== 主程序 ==========

main() {
    local command="${1:-build}"
    shift || true

    case "${command}" in
        setup)
            cmd_setup
            ;;
        build)
            check_docker
            run_build_container "$@"
            ;;
        shell)
            check_docker
            cmd_shell
            ;;
        clean)
            check_docker
            cmd_clean
            ;;
        exec)
            check_docker
            cmd_exec "$@"
            ;;
        help|-h|--help)
            print_usage
            ;;
        *)
            echo "错误: 未知命令 '${command}'"
            echo ""
            print_usage
            exit 1
            ;;
    esac
}

main "$@"
