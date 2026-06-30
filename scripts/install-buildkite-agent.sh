#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Buildkite Agent macOS 安装脚本 (适用于 GitCode)

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
Buildkite Agent macOS 安装脚本 (适用于 GitCode)

使用方法: bash $0

环境变量:
  BUILDKITE_AGENT_TOKEN  - Agent Token (必需)
  BUILDKITE_AGENT_NAME   - Agent 名称 (默认: macos-arm64-builder)

获取步骤:
  1. 访问 https://buildkite.com/sign-up
  2. 注册/登录后创建组织
  3. Agents → New Agent → Generic → 复制 Token

示例:
  export BUILDKITE_AGENT_TOKEN=xxx
  bash $0
EOF
}

# 检查 macOS
check_macos() {
    if [[ "$(uname)" != "Darwin" ]]; then
        log_error "此脚本只能在 macOS 上运行"
        exit 1
    fi
    log_info "检测到 macOS: $(sw_vers -productName) $(sw_vers -productVersion)"
}

# 检查 Agent Token
check_token() {
    if [ -z "$BUILDKITE_AGENT_TOKEN" ]; then
        log_error "BUILDKITE_AGENT_TOKEN 未设置"
        echo ""
        echo "请先设置环境变量:"
        echo "  export BUILDKITE_AGENT_TOKEN=your-token-here"
        echo ""
        echo "获取 Token 步骤:"
        echo "  1. 访问 https://buildkite.com/sign-up"
        echo "  2. 注册/登录"
        echo "  3. Agents → New Agent → Generic"
        echo "  4. 复制 Agent Token"
        exit 1
    fi
}

# 检查 Homebrew
check_brew() {
    if ! command -v brew &> /dev/null; then
        log_error "Homebrew 未安装"
        echo ""
        echo "请先安装 Homebrew:"
        echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        exit 1
    fi
    log_info "Homebrew: $(brew --version | head -1)"
}

# 安装 Agent
install_agent() {
    log_step "安装 Buildkite Agent..."

    if brew list buildkite-agent &> /dev/null; then
        log_warn "Buildkite Agent 已安装，更新中..."
        brew upgrade buildkite-agent
    else
        brew tap buildkite/buildkite
        brew install buildkite-agent
    fi

    log_info "Buildkite Agent: $(buildkite-agent --version)"
}

# 创建目录（创建 hooks 和 plugins 目录）
create_build_dirs() {
    log_step "创建构建目录..."

    # 检测 Homebrew 路径
    local homebrew_prefix=""
    if [ -d "/opt/homebrew" ]; then
        homebrew_prefix="/opt/homebrew"
    elif [ -d "/usr/local" ]; then
        homebrew_prefix="/usr/local"
    else
        log_error "无法找到 Homebrew 安装路径"
        exit 1
    fi

    # 使用 Homebrew var 目录，避免权限问题
    local hooks_path="${homebrew_prefix}/var/buildkite-agent/hooks"
    local plugins_path="${homebrew_prefix}/var/buildkite-agent/plugins"
    local build_path="/var/buildkite-builds"

    # 创建 hooks 目录
    if [ ! -d "$hooks_path" ]; then
        sudo mkdir -p "$hooks_path"
        sudo chown -R $USER:staff "${homebrew_prefix}/var/buildkite-agent"
        log_info "Hooks 目录: $hooks_path"
    fi

    # 创建 plugins 目录
    if [ ! -d "$plugins_path" ]; then
        sudo mkdir -p "$plugins_path"
        sudo chown -R $USER:staff "${homebrew_prefix}/var/buildkite-agent"
        log_info "Plugins 目录: $plugins_path"
    fi

    # 创建构建目录
    if [ ! -d "$build_path" ]; then
        sudo mkdir -p "$build_path"
        sudo chown $USER:staff "$build_path"
        log_info "构建目录: $build_path"
    fi
}

# 配置 Agent
configure_agent() {
    log_step "配置 Buildkite Agent..."

    local agent_name="${BUILDKITE_AGENT_NAME:-macos-arm64-builder}"

    # 检测 Homebrew 路径
    local homebrew_prefix=""
    if [ -d "/opt/homebrew" ]; then
        homebrew_prefix="/opt/homebrew"
    elif [ -d "/usr/local" ]; then
        homebrew_prefix="/usr/local"
    else
        log_error "无法找到 Homebrew 安装路径"
        exit 1
    fi

    local config_dir="${homebrew_prefix}/etc/buildkite-agent"
    local config_file="${config_dir}/buildkite-agent.cfg"
    local hooks_path="${homebrew_prefix}/var/buildkite-agent/hooks"
    local plugins_path="${homebrew_prefix}/var/buildkite-agent/plugins"

    # 使用 sudo 创建配置目录和文件
    sudo mkdir -p "$config_dir"

    cat << EOF | sudo tee "$config_file" > /dev/null
# Buildkite Agent 配置
# 生成时间: $(date)

# Agent Token
token="${BUILDKITE_AGENT_TOKEN}"

# Agent 名称
name="${agent_name}"

# Agent 标签 (用于 Pipeline 选择)
# 注意: 不要同时设置 meta-data，会冲突
tags=os=macos,arch=arm64,docker=true

# 队列名称 (必需，如果组织启用了 Queue)
# 去 Buildkite Dashboard → Settings → Agents → Queues 查看
queue=default

# 构建路径
build-path=/var/buildkite-builds

# Hooks 路径（使用 Homebrew var 目录）
hooks-path=${hooks_path}

# Plugins 路径（使用 Homebrew var 目录，避免权限问题）
plugins-path=${plugins_path}

# 并发构建数
spawn=2

# 保持长连接（不自动断开）
# disconnect-after-job=true
# disconnect-after-idle-timeout=300
EOF

    # 修复文件权限
    sudo chmod 640 "$config_file"
    sudo chown root:admin "$config_file"

    log_info "Homebrew 路径: $homebrew_prefix"
    log_info "配置文件: $config_file"
    log_info "Hooks 目录: $hooks_path"
    log_info "Plugins 目录: $plugins_path"
    log_info "Agent 名称: $agent_name"
}

# 启动 Agent
start_agent() {
    log_step "启动 Buildkite Agent..."

    # 注册服务
    if ! brew services list | grep -q "buildkite-agent.*started"; then
        brew services start buildkite/buildkite/buildkite-agent
        log_info "Agent 服务已启动"
    else
        brew services restart buildkite/buildkite/buildkite-agent
        log_info "Agent 服务已重启"
    fi

    sleep 3
}

# 验证 Agent
verify_agent() {
    log_step "验证 Agent 状态..."

    if buildkite-agent status &> /dev/null; then
        log_info "✓ Agent 运行正常"
        echo ""
        buildkite-agent status
    else
        log_error "Agent 运行异常"
        echo ""
        log_warn "查看日志:"
        log_warn "  tail -f ~/Library/Logs/buildkite-agent/buildkite-agent.log"
        return 1
    fi
}

# 显示完成信息
show_completion() {
    cat << EOF

${GREEN}========================================${NC}
${GREEN}  Buildkite Agent 安装完成!${NC}
${GREEN}========================================${NC}

${BLUE}下一步:${NC}

1. ${BLUE}在 Buildkite 创建 Pipeline${NC}
   Dashboard → Pipelines → New Pipeline
   → 选择: Generic
   → Repository: https://gitcode.com/xxx/xxx.git

2. ${BLUE}配置 GitCode Webhook${NC}
   GitCode → 设置 → Webhooks
   → URL: (从 Buildkite Pipeline Settings 复制)

3. ${BLUE}推送代码触发构建${NC}
   git push origin main

${BLUE}常用命令:${NC}
  buildkite-agent status    # 查看状态
  brew services restart ... # 重启服务

${BLUE}查看日志:${NC}
  tail -f /opt/homebrew/var/log/buildkite-agent.log

${BLUE}配置文件:${NC}
  /opt/homebrew/etc/buildkite-agent/buildkite-agent.cfg

${BLUE}Hooks/Plugins 目录:${NC}
  /opt/homebrew/var/buildkite-agent/hooks
  /opt/homebrew/var/buildkite-agent/plugins

${GREEN}========================================${NC}

${BLUE}如果遇到插件权限问题:${NC}
  sudo chown -R $USER:staff /opt/homebrew/var/buildkite-agent
  brew services restart buildkite/buildkite/buildkite-agent

${GREEN}========================================${NC}
EOF
}

# ========== 主程序 ==========

main() {
    cat << EOF
${BLUE}========================================${NC}
${BLUE}  Buildkite Agent macOS 安装向导${NC}
${BLUE}  适用于 GitCode${NC}
${BLUE}========================================${NC}
EOF

    check_macos
    check_token
    check_brew

    echo ""
    install_agent
    echo ""
    create_build_dirs
    echo ""
    configure_agent
    echo ""
    start_agent
    echo ""
    verify_agent
    echo ""

    if [ $? -eq 0 ]; then
        show_completion
    fi
}

main "$@"
