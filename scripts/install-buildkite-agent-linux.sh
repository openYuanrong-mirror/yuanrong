#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Buildkite Agent Linux 安装脚本

set -e

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
  setup   - 初始化配置 (设置 Token)
  install - 安装并启动 Agent
  start   - 启动 Agent
  stop    - 停止 Agent
  restart - 重启 Agent
  status  - 查看状态
  logs    - 查看日志
  uninstall - 卸载 Agent

环境变量:
  BUILDKITE_AGENT_TOKEN   - Agent Token (必需)
  BUILDKITE_AGENT_NAME    - Agent 名称 (默认: linux-arm64-builder)
  BUILDKITE_AGENT_QUEUE   - 队列名称 (默认: default)

获取 Agent Token:
  https://buildkite.com/organizations/<org>/agents/new

示例:
  export BUILDKITE_AGENT_TOKEN=xxx
  $0 install
EOF
}

# 检测系统
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        OS_VERSION=$VERSION_ID
    elif [ -f /etc/redhat-release ]; then
        OS="rhel"
    elif [ -f /etc/debian_version ]; then
        OS="debian"
    else
        log_error "无法检测操作系统"
        exit 1
    fi

    log_info "检测到系统: $OS"

    # 检测架构
    ARCH=$(uname -m)
    log_info "架构: $ARCH"
}

# 检查 Token
check_token() {
    if [ -z "$BUILDKITE_AGENT_TOKEN" ]; then
        log_error "BUILDKITE_AGENT_TOKEN 未设置"
        echo ""
        echo "请先设置环境变量:"
        echo "  export BUILDKITE_AGENT_TOKEN=your-token-here"
        echo ""
        echo "获取 Token: https://buildkite.com/organizations/<org>/agents/new"
        exit 1
    fi
}

# 安装依赖
install_dependencies() {
    log_step "安装依赖..."

    case "$OS" in
        ubuntu|debian)
            sudo apt-get update
            sudo apt-get install -y wget curl git
            ;;
        centos|rhel|fedora|rocky|almalinux)
            sudo dnf install -y wget curl git || \
            sudo yum install -y wget curl git
            ;;
        opensuse*)
            sudo zypper install -y wget curl git
            ;;
        *)
            log_warn "未知系统 $OS，跳过依赖安装"
            ;;
    esac
}

# 下载并安装 Agent
install_agent() {
    log_step "下载并安装 Buildkite Agent..."

    # 检测架构对应的包
    case "$ARCH" in
        x86_64)
            AGENT_ARCH="amd64"
            ;;
        aarch64|arm64)
            AGENT_ARCH="arm64"
            ;;
        *)
            log_error "不支持的架构: $ARCH"
            exit 1
            ;;
    esac

    # 下载最新版本
    AGENT_VERSION="3.120.1"
    DOWNLOAD_URL="https://github.com/buildkite/agent/releases/download/v${AGENT_VERSION}/buildkite-agent-linux-${AGENT_VERSION}-${AGENT_ARCH}.tar.gz"

    log_info "下载: $DOWNLOAD_URL"

    # 创建临时目录
    TMP_DIR=$(mktemp -d)
    cd "$TMP_DIR"

    # 下载
    wget -O "buildkite-agent.tar.gz" "$DOWNLOAD_URL"

    # 解压
    tar -xzf "buildkite-agent.tar.gz"

    # 安装
    sudo mkdir -p /usr/local/bin
    sudo cp "buildkite-agent" /usr/local/bin/
    sudo chmod +x /usr/local/bin/buildkite-agent

    # 创建链接
    sudo ln -sf /usr/local/bin/buildkite-agent /usr/bin/buildkite-agent

    # 清理
    cd -
    rm -rf "$TMP_DIR"

    log_info "Buildkite Agent: $(buildkite-agent --version)"
}

# 创建用户
create_user() {
    log_step "创建 buildkite-agent 用户..."

    if ! id buildkite-agent &>/dev/null; then
        sudo useradd -d /var/lib/buildkite-agent -m -s /bin/bash buildkite-agent
        log_info "用户 buildkite-agent 已创建"
    else
        log_info "用户 buildkite-agent 已存在"
    fi
}

# 配置 Agent
configure_agent() {
    log_step "配置 Buildkite Agent..."

    local agent_name="${BUILDKITE_AGENT_NAME:-linux-${ARCH}-builder}"
    local queue="${BUILDKITE_AGENT_QUEUE:-default}"

    local config_dir="/etc/buildkite-agent"
    local config_file="${config_dir}/buildkite-agent.cfg"

    sudo mkdir -p "$config_dir"

    sudo tee "$config_file" > /dev/null << EOF
# Buildkite Agent 配置
# 生成时间: $(date)

# Agent Token
token="${BUILDKITE_AGENT_TOKEN}"

# Agent 名称
name="${agent_name}"

# Agent 标签
tags=os=linux,arch=${ARCH},docker=true

# 队列名称
queue=${queue}

# 构建路径
build-path=/var/lib/buildkite-agent/builds

# Hooks 路径
hooks-path=/etc/buildkite-agent/hooks

# Plugins 路径
plugins-path=/etc/buildkite-agent/plugins

# 并发构建数
spawn=2

# 保持长连接（不自动断开）
# disconnect-after-job=true
# disconnect-after-idle-timeout=300

# 在后台运行
daemon=true
EOF

    # 创建 hooks 和 plugins 目录
    sudo mkdir -p /etc/buildkite-agent/hooks
    sudo mkdir -p /etc/buildkite-agent/plugins
    sudo chown -R buildkite-agent:buildkite-agent /etc/buildkite-agent

    # 设置权限
    sudo chmod 640 "$config_file"
    sudo chown root:buildkite-agent "$config_file"

    log_info "配置文件: $config_file"
    log_info "Hooks 目录: /etc/buildkite-agent/hooks"
    log_info "Plugins 目录: /etc/buildkite-agent/plugins"
    log_info "Agent 名称: $agent_name"
    log_info "队列: $queue"
}

# 创建 systemd 服务
create_service() {
    log_step "创建 systemd 服务..."

    sudo tee /etc/systemd/system/buildkite-agent.service > /dev/null << 'EOF'
[Unit]
Description=Buildkite Agent
After=network.target

[Service]
User=buildkite-agent
Group=buildkite-agent
Type=simple

# Environment file
EnvironmentFile=/etc/buildkite-agent/environment

# ExecStart
ExecStart=/usr/bin/buildkite-agent start

# ExecStop
ExecStop=/usr/bin/buildkite-agent stop

# Restart
Restart=always
RestartSec=5

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    # 创建环境文件
    sudo tee /etc/buildkite-agent/environment > /dev/null << EOF
# Buildkite Agent 环境变量
BUILDKITE_AGENT_CONFIG=/etc/buildkite-agent/buildkite-agent.cfg
BUILDKITE_AGENT_HOME=/var/lib/buildkite-agent
EOF

    sudo systemctl daemon-reload

    log_info "systemd 服务已创建"
}

# 启动 Agent
cmd_start() {
    log_info "启动 Buildkite Agent..."

    sudo systemctl enable buildkite-agent
    sudo systemctl start buildkite-agent

    sleep 3

    log_info "Agent 状态:"
    sudo systemctl status buildkite-agent --no-pager
}

# 停止 Agent
cmd_stop() {
    log_info "停止 Buildkite Agent..."
    sudo systemctl stop buildkite-agent
    log_info "Agent 已停止"
}

# 重启 Agent
cmd_restart() {
    log_info "重启 Buildkite Agent..."
    sudo systemctl restart buildkite-agent
    sleep 2
    cmd_status
}

# 查看状态
cmd_status() {
    sudo systemctl status buildkite-agent --no-pager
}

# 查看日志
cmd_logs() {
    sudo journalctl -u buildkite-agent -f
}

# 初始化配置
cmd_setup() {
    check_token
    log_info "配置已就绪"
    log_info "Token: ${BUILDKITE_AGENT_TOKEN:0:8}..."
    log_info "运行 '$0 install' 安装 Agent"
}

# 完整安装
cmd_install() {
    cat << EOF
${BLUE}========================================${NC}
${BLUE}  Buildkite Agent Linux 安装向导${NC}
${BLUE}========================================${NC}
EOF

    check_token
    detect_os
    install_dependencies
    install_agent
    create_user
    configure_agent
    create_service
    cmd_start

    cat << EOF

${GREEN}========================================${NC}
${GREEN}  Buildkite Agent 安装完成!${NC}
${GREEN}========================================${NC}

${BLUE}常用命令:${NC}
  $0 start    # 启动 Agent
  $0 stop     # 停止 Agent
  $0 restart  # 重启 Agent
  $0 status   # 查看状态
  $0 logs     # 查看日志

${BLUE}配置文件:${NC}
  /etc/buildkite-agent/buildkite-agent.cfg

${BLUE}查看状态:${NC}
  systemctl status buildkite-agent

${BLUE}查看日志:${NC}
  journalctl -u buildkite-agent -f

${GREEN}========================================${NC}
EOF
}

# 卸载
cmd_uninstall() {
    log_warn "准备卸载 Buildkite Agent..."
    read -p "确认卸载? (y/N): " confirm

    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "已取消"
        return
    fi

    log_info "停止服务..."
    sudo systemctl stop buildkite-agent
    sudo systemctl disable buildkite-agent

    log_info "删除服务..."
    sudo rm -f /etc/systemd/system/buildkite-agent.service
    sudo systemctl daemon-reload

    log_info "删除文件..."
    sudo rm -rf /etc/buildkite-agent
    sudo rm -f /usr/local/bin/buildkite-agent
    sudo rm -f /usr/bin/buildkite-agent

    log_info "删除用户和目录..."
    sudo userdel buildkite-agent 2>/dev/null || true
    sudo rm -rf /var/lib/buildkite-agent

    log_info "卸载完成"
}

# 主程序
main() {
    local command="${1:-install}"

    case "${command}" in
        setup)     cmd_setup ;;
        install)   cmd_install ;;
        start)     cmd_start ;;
        stop)      cmd_stop ;;
        restart)   cmd_restart ;;
        status)    cmd_status ;;
        logs)      cmd_logs ;;
        uninstall) cmd_uninstall ;;
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
