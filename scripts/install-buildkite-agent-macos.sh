#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Buildkite Agent macOS 安装脚本

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $*"; }

BREW_PREFIX=""
CFG_DIR=""
CFG_FILE=""

print_usage() {
    cat << EOF
使用方法: bash $0 [command]

命令:
  setup      - 初始化配置 (设置 Token 并生成配置文件)
  install    - 安装 Buildkite Agent 并生成配置文件
  start      - 前台启动 Agent
  stop       - 停止 brew service 管理的 Agent
  restart    - 重启 brew service 管理的 Agent
  status     - 查看 Agent 状态
  logs       - 查看 Agent 日志
  service    - 使用 brew services 启动 Agent
  uninstall  - 卸载 Agent

环境变量:
  BUILDKITE_AGENT_TOKEN   - Agent Token (setup/install 时必需)
  BUILDKITE_AGENT_NAME    - Agent 名称 (默认: macos-arm64-builder)
  BUILDKITE_AGENT_QUEUE   - 队列名称 (默认: default)
  BUILDKITE_AGENT_TAGS    - Agent 标签 (默认: os=macos,arch=arm64)
  BUILDKITE_AGENT_CONFIG  - 配置文件路径 (默认: <brew-prefix>/etc/buildkite-agent/buildkite-agent.cfg)
  BUILDKITE_AGENT_BUILD_PATH - 构建目录 (默认: /var/buildkite-builds)
  BUILDKITE_AGENT_HOOKS_PATH - Hooks 目录 (默认: /etc/buildkite-hooks)

获取 Agent Token:
  https://buildkite.com/organizations/<org>/agents/new

示例:
  export BUILDKITE_AGENT_TOKEN=xxx
  bash $0 install
  bash $0 service
EOF
}

detect_paths() {
    if [[ "$(uname -s)" != "Darwin" ]]; then
        log_error "此脚本仅支持 macOS"
        exit 1
    fi
    if ! command -v brew >/dev/null 2>&1; then
        log_error "Homebrew 未安装"
        exit 1
    fi
    BREW_PREFIX="$(brew --prefix)"
    CFG_DIR="$(dirname "${BUILDKITE_AGENT_CONFIG:-${BREW_PREFIX}/etc/buildkite-agent/buildkite-agent.cfg}")"
    CFG_FILE="${BUILDKITE_AGENT_CONFIG:-${BREW_PREFIX}/etc/buildkite-agent/buildkite-agent.cfg}"
}

check_token() {
    if [[ -z "${BUILDKITE_AGENT_TOKEN:-}" ]]; then
        log_error "BUILDKITE_AGENT_TOKEN 未设置"
        echo ""
        echo "请先设置环境变量:"
        echo "  export BUILDKITE_AGENT_TOKEN=your-token-here"
        echo ""
        echo "获取 Token: https://buildkite.com/organizations/<org>/agents/new"
        exit 1
    fi
}

ensure_agent_installed() {
    if command -v buildkite-agent >/dev/null 2>&1; then
        log_info "Buildkite Agent 已安装: $(buildkite-agent --version)"
        return
    fi

    log_step "安装 Buildkite Agent..."
    brew install buildkite/buildkite/buildkite-agent
    log_info "Buildkite Agent 已安装: $(buildkite-agent --version)"
}

write_config() {
    check_token
    mkdir -p "$CFG_DIR"

    local agent_name="${BUILDKITE_AGENT_NAME:-macos-arm64-builder}"
    local queue="${BUILDKITE_AGENT_QUEUE:-default}"
    local tags="${BUILDKITE_AGENT_TAGS:-os=macos,arch=arm64}"
    local build_path="${BUILDKITE_AGENT_BUILD_PATH:-/var/buildkite-builds}"
    local hooks_path="${BUILDKITE_AGENT_HOOKS_PATH:-/etc/buildkite-hooks}"

    cat > "$CFG_FILE" << EOF
# Buildkite Agent 配置
# 生成时间: $(date)

token="${BUILDKITE_AGENT_TOKEN}"
name="${agent_name}"
tags=${tags}
queue=${queue}
build-path=${build_path}
hooks-path=${hooks_path}
spawn=1
disconnect-after-job=true
disconnect-after-idle-timeout=300
EOF

    log_info "配置文件已写入: $CFG_FILE"
}

cmd_setup() {
    detect_paths
    ensure_agent_installed
    write_config
}

cmd_install() {
    detect_paths
    ensure_agent_installed
    write_config
}

cmd_start() {
    detect_paths
    if ! command -v buildkite-agent >/dev/null 2>&1; then
        log_error "buildkite-agent 未安装，请先执行: bash $0 install"
        exit 1
    fi
    if [[ ! -f "$CFG_FILE" ]]; then
        log_error "配置文件不存在: $CFG_FILE"
        exit 1
    fi
    log_info "以前台模式启动 Agent..."
    exec buildkite-agent start --config "$CFG_FILE"
}

cmd_service() {
    detect_paths
    if [[ ! -f "$CFG_FILE" ]]; then
        log_error "配置文件不存在: $CFG_FILE"
        exit 1
    fi
    log_info "使用 brew services 启动 Agent..."
    brew services start buildkite/buildkite/buildkite-agent
    cmd_status
}

cmd_stop() {
    detect_paths
    brew services stop buildkite/buildkite/buildkite-agent
}

cmd_restart() {
    detect_paths
    brew services restart buildkite/buildkite/buildkite-agent
    cmd_status
}

cmd_status() {
    detect_paths
    echo "=== Buildkite Agent ==="
    command -v buildkite-agent >/dev/null 2>&1 && buildkite-agent --version || true
    echo ""
    echo "=== Brew Services ==="
    brew services list | grep -i buildkite || true
    echo ""
    echo "=== Config ==="
    if [[ -f "$CFG_FILE" ]]; then
        echo "$CFG_FILE"
        sed -n '1,40p' "$CFG_FILE"
    else
        echo "missing: $CFG_FILE"
    fi
}

cmd_logs() {
    detect_paths
    local log_file="${BREW_PREFIX}/var/log/buildkite-agent.log"
    if [[ -f "$log_file" ]]; then
        tail -f "$log_file"
    else
        log_warn "未找到日志文件: $log_file"
    fi
}

cmd_uninstall() {
    detect_paths
    brew services stop buildkite/buildkite/buildkite-agent || true
    brew uninstall buildkite-agent || true
}

main() {
    local command="${1:-setup}"
    case "$command" in
        setup) cmd_setup ;;
        install) cmd_install ;;
        start) cmd_start ;;
        stop) cmd_stop ;;
        restart) cmd_restart ;;
        status) cmd_status ;;
        logs) cmd_logs ;;
        service) cmd_service ;;
        uninstall) cmd_uninstall ;;
        help|-h|--help) print_usage ;;
        *)
            log_error "未知命令: ${command}"
            echo ""
            print_usage
            exit 1
            ;;
    esac
}

main "$@"
