#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Start or restart the Homebrew Buildkite agent on macOS.

set -euo pipefail

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

check_macos() {
    if [[ "$(uname)" != "Darwin" ]]; then
        log_error "This script only supports macOS"
        exit 1
    fi
}

check_brew() {
    if ! command -v brew >/dev/null 2>&1; then
        log_error "Homebrew is required"
        exit 1
    fi
}

ensure_agent_installed() {
    if ! command -v buildkite-agent >/dev/null 2>&1; then
        log_step "Buildkite agent is not installed yet, delegating to install-buildkite-agent.sh"
        bash "${SCRIPT_DIR}/install-buildkite-agent.sh"
        return
    fi

    local config_file
    config_file="$(brew --prefix)/etc/buildkite-agent/buildkite-agent.cfg"
    if [[ ! -f "${config_file}" ]]; then
        log_step "Buildkite agent config missing, delegating to install-buildkite-agent.sh"
        bash "${SCRIPT_DIR}/install-buildkite-agent.sh"
    fi
}

start_agent() {
    log_step "Starting Buildkite agent service"
    if brew services list | grep -q "buildkite-agent.*started"; then
        brew services restart buildkite/buildkite/buildkite-agent
    else
        brew services start buildkite/buildkite/buildkite-agent
    fi
}

show_status() {
    log_step "Agent status"
    buildkite-agent status || true
    echo
    brew services list | grep buildkite-agent || true
}

main() {
    check_macos
    check_brew
    ensure_agent_installed
    start_agent
    show_status
    log_info "Buildkite agent is ready"
}

main "$@"
