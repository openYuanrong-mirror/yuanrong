#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Woodpecker CI 快速设置脚本 - 完全免费开源的 CI/CD

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $*"; }

print_usage() {
    cat << EOF
使用方法: bash $0 [command]

命令:
  setup     - 初始化配置 (设置 GitHub OAuth)
  start     - 启动 Woodpecker 服务
  stop      - 停止服务
  restart   - 重启服务
  logs      - 查看日志
  status    - 查看状态
  url       - 获取访问信息

环境变量:
  WOODPECKER_HOST          - 服务访问地址 (如: http://localhost:8000)
  WOODPECKER_GITHUB_CLIENT - GitHub OAuth Client ID
  WOODPECKER_GITHUB_SECRET - GitHub OAuth Client Secret
  WOODPECKER_AGENT_SECRET  - Agent 密钥

获取 GitHub OAuth:
  1. 访问 https://github.com/settings/developers
  2. 点击 "New OAuth App"
  3. 填写:
     - Application name: Woodpecker CI
     - Homepage URL: http://localhost:8000
     - Authorization callback URL: http://localhost:8000/authorize
  4. 创建后获取 Client ID 和 Secret

示例:
  # 设置环境变量
  export WOODPECKER_HOST=http://localhost:8000
  export WOODPECKER_GITHUB_CLIENT=xxx
  export WOODPECKER_GITHUB_SECRET=xxx
  export WOODPECKER_AGENT_SECRET=$(openssl rand -hex 32)

  # 初始化并启动
  $0 setup
  $0 start
EOF
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装"
        exit 1
    fi
    docker info &> /dev/null || { log_error "Docker 未运行"; exit 1; }
}

# 初始化配置
cmd_setup() {
    log_info "=== Woodpecker CI 初始化 ==="
    echo ""

    # 检查环境变量
    if [ -z "$WOODPECKER_GITHUB_CLIENT" ] || [ -z "$WOODPECKER_GITHUB_SECRET" ]; then
        log_error "GitHub OAuth 凭据未设置"
        echo ""
        echo "请先设置环境变量:"
        echo "  export WOODPECKER_HOST=http://localhost:8000"
        echo "  export WOODPECKER_GITHUB_CLIENT=your-client-id"
        echo "  export WOODPECKER_GITHUB_SECRET=your-client-secret"
        echo "  export WOODPECKER_AGENT_SECRET=\$(openssl rand -hex 32)"
        echo ""
        echo "获取 GitHub OAuth 步骤:"
        echo "  1. 访问 https://github.com/settings/developers"
        echo "  2. 点击 'New OAuth App'"
        echo "  3. Callback URL: http://localhost:8000/authorize"
        exit 1
    fi

    check_docker

    # 生成随机密钥（如果未设置）
    local agent_secret="${WOODPECKER_AGENT_SECRET:-$(openssl rand -hex 32)}"
    local db_secret="$(openssl rand -hex 32)"

    # 创建 .env 文件
    cat > "${SCRIPT_DIR}/.woodpecker.env" << EOF
# Woodpecker CI 配置
WOODPECKER_HOST=${WOODPECKER_HOST:-http://localhost:8000}
WOODPECKER_GITHUB_CLIENT=${WOODPECKER_GITHUB_CLIENT}
WOODPECKER_GITHUB_SECRET=${WOODPECKER_GITHUB_SECRET}
WOODPECKER_AGENT_SECRET=${agent_secret}
WOODPECKER_DATABASE_SECRET=${db_secret}
EOF

    log_info "配置文件已创建: ${SCRIPT_DIR}/.woodpecker.env"
    echo ""
    log_info "下一步: $0 start"
}

# 启动服务
cmd_start() {
    log_info "启动 Woodpecker CI..."

    check_docker

    # 加载环境变量
    if [ -f "${SCRIPT_DIR}/.woodpecker.env" ]; then
        set -a
        source "${SCRIPT_DIR}/.woodpecker.env"
        set +a
    fi

    cd "${SCRIPT_DIR}"
    docker-compose -f docker-compose.woodpecker.yml up -d

    log_info "Woodpecker CI 启动中，请稍等..."
    sleep 5

    cmd_url
}

# 停止服务
cmd_stop() {
    log_info "停止 Woodpecker CI..."

    cd "${SCRIPT_DIR}"
    docker-compose -f docker-compose.woodpecker.yml down

    log_info "Woodpecker CI 已停止"
}

# 重启服务
cmd_restart() {
    cmd_stop
    sleep 2
    cmd_start
}

# 查看日志
cmd_logs() {
    cd "${SCRIPT_DIR}"
    docker-compose -f docker-compose.woodpecker.yml logs -f
}

# 查看状态
cmd_status() {
    cd "${SCRIPT_DIR}"
    docker-compose -f docker-compose.woodpecker.yml ps
}

# 获取访问信息
cmd_url() {
    log_info "=========================================="
    log_info "  Woodpecker CI 访问信息"
    log_info "=========================================="

    cd "${SCRIPT_DIR}"
    if docker-compose -f docker-compose.woodpecker.yml ps | grep -q "yr-woodpecker-server.*Up"; then
        local host="${WOODPECKER_HOST:-http://localhost:8000}"
        log_info "状态: 运行中"
        log_info "Web UI: ${host}"
        echo ""
        log_info "=========================================="
        log_info "  下一步操作"
        log_info "=========================================="
        log_info "1. 访问 ${host}"
        log_info "2. 使用 GitHub 账号登录"
        log_info "3. 激活你的仓库"
        log_info "4. 推送代码触发构建"
        log_info "=========================================="
    else
        log_warn "状态: 未运行"
        log_info "请先执行: $0 start"
    fi
}

# 主程序
main() {
    local command="${1:-setup}"

    case "${command}" in
        setup)   cmd_setup ;;
        start)   cmd_start ;;
        stop)    cmd_stop ;;
        restart) cmd_restart ;;
        logs)    cmd_logs ;;
        status)  cmd_status ;;
        url)     cmd_url ;;
        help|-h|--help)
            print_usage
            ;;
        *)
            log_error "未知命令: ${command}"
            echo ""
            print_usage
            exit 1
            ;;
    esac
}

main "$@"
