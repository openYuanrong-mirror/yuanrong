#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Jenkins CI/CD 快速设置脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

print_usage() {
    cat << EOF
使用方法: bash $0 [command]

命令:
  start     - 启动 Jenkins 服务
  stop      - 停止 Jenkins 服务
  restart   - 重启 Jenkins 服务
  logs      - 查看 Jenkins 日志
  url       - 获取 Jenkins 访问地址和初始密码
  setup     - 初始化 Jenkins (安装插件)

环境变量:
  JENKINS_PORT     - Jenkins Web 端口 (默认: 8080)
  JENKINS_PASSWORD - Admin 密码 (默认: admin123)

示例:
  # 启动 Jenkins
  $0 start

  # 查看日志
  $0 logs

  # 获取访问信息
  $0 url
EOF
}

# 检查 Docker
check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装"
        exit 1
    fi

    if ! docker info &> /dev/null; then
        log_error "Docker 未运行"
        exit 1
    fi
}

# 启动 Jenkins
cmd_start() {
    log_info "启动 Jenkins..."

    check_docker

    cd "${SCRIPT_DIR}"
    docker-compose -f docker-compose.jenkins.yml up -d

    log_info "Jenkins 启动中，请稍等..."
    sleep 5

    cmd_url
}

# 停止 Jenkins
cmd_stop() {
    log_info "停止 Jenkins..."

    cd "${SCRIPT_DIR}"
    docker-compose -f docker-compose.jenkins.yml down

    log_info "Jenkins 已停止"
}

# 重启 Jenkins
cmd_restart() {
    log_info "重启 Jenkins..."
    cmd_stop
    sleep 2
    cmd_start
}

# 查看日志
cmd_logs() {
    cd "${SCRIPT_DIR}"
    docker-compose -f docker-compose.jenkins.yml logs -f jenkins
}

# 获取访问信息
cmd_url() {
    local port="${JENKINS_PORT:-8080}"
    local container="yr-jenkins"

    log_info "=========================================="
    log_info "  Jenkins 访问信息"
    log_info "=========================================="

    # 检查容器是否运行
    if docker ps --filter "name=${container}" --format '{{.Names}}' | grep -q "^${container}$"; then
        log_info "状态: 运行中"
    else
        log_warn "状态: 未运行"
        log_info "请先执行: $0 start"
        return
    fi

    echo ""
    log_info "Web UI: http://localhost:${port}"
    log_info "用户名: admin"

    # 获取初始密码
    local password=$(docker exec ${container} cat /var/jenkins_home/secrets/initialAdminPassword 2>/dev/null || echo "")
    if [ -n "$password" ]; then
        log_info "初始密码: ${password}"
    fi

    echo ""
    log_info "=========================================="
    log_info "  下一步操作"
    log_info "=========================================="
    log_info "1. 访问 http://localhost:${port}"
    log_info "2. 解锁 Jenkins (输入初始密码)"
    log_info "3. 安装推荐插件"
    log_info "4. 创建管理员用户"
    log_info "5. 创建 Pipeline 任务，使用仓库中的 Jenkinsfile"
    log_info ""
    log_info "配置 macOS 构建节点:"
    log_info "  Manage Jenkins → Manage Nodes and Clouds → New Node"
    log_info "=========================================="
}

# 初始化 Jenkins (可选配置)
cmd_setup() {
    log_info "Jenkins 初始化配置..."

    log_info "请按以下步骤操作:"
    log_info ""
    log_info "1. 访问 Jenkins Web UI 并完成初始化"
    log_info "2. 安装以下插件:"
    log_info "   - Docker Pipeline"
    log_info "   - SSH Agent Plugin"
    log_info "   - Git Parameter Plugin"
    log_info "   - Timestamper Plugin"
    log_info "   - Workspace Cleanup Plugin"
    log_info ""
    log_info "3. 配置 macOS 构建节点:"
    log_info "   Manage Jenkins → Manage Nodes and Clouds"
    log_info "   → New Node → Permanent Agent"
    log_info ""
    log_info "   节点配置:"
    log_info "   - Name: macos-arm64"
    log_info "   - Launch method: Launch agent via SSH"
    log_info "   - Host: <macOS IP>"
    log_info "   - Credentials: macOS SSH 密钥"
    log_info ""
}

# ========== 主程序 ==========

main() {
    local command="${1:-start}"

    case "${command}" in
        start)
            cmd_start
            ;;
        stop)
            cmd_stop
            ;;
        restart)
            cmd_restart
            ;;
        logs)
            cmd_logs
            ;;
        url)
            cmd_url
            ;;
        setup)
            cmd_setup
            ;;
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
