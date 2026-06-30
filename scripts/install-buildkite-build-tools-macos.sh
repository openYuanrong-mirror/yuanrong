#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Install the software prerequisites needed to build the macOS SDK with:
#   bash build.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

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

check_xcode_cli() {
    if ! xcode-select -p >/dev/null 2>&1; then
        log_error "Xcode Command Line Tools are required"
        echo "Run: xcode-select --install"
        exit 1
    fi
}

check_brew() {
    if ! command -v brew >/dev/null 2>&1; then
        log_error "Homebrew is required"
        echo 'Run: /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        exit 1
    fi
}

brew_install() {
    local formula="$1"
    if brew list --versions "$formula" >/dev/null 2>&1; then
        log_info "$formula already installed"
        return
    fi
    brew install "$formula"
}

configure_bazel() {
    local brew_bin
    brew_bin="$(brew --prefix)/bin"
    if command -v bazel >/dev/null 2>&1; then
        return
    fi
    if command -v bazelisk >/dev/null 2>&1; then
        ln -sf "$(command -v bazelisk)" "${brew_bin}/bazel"
        log_info "Linked bazel -> bazelisk"
    fi
}

write_environment_hook() {
    local brew_prefix hook_dir hook_file
    brew_prefix="$(brew --prefix)"
    hook_dir="${brew_prefix}/var/buildkite-agent/hooks"
    hook_file="${hook_dir}/environment"

    sudo mkdir -p "${hook_dir}"
    sudo tee "${hook_file}" >/dev/null <<EOF
#!/bin/bash
export HOMEBREW_PREFIX="${brew_prefix}"
export PATH="${brew_prefix}/bin:${brew_prefix}/sbin:${brew_prefix}/opt/openjdk@17/bin:${brew_prefix}/opt/python@3.11/libexec/bin:\$PATH"
export JAVA_HOME="\$(/usr/libexec/java_home -v 17 2>/dev/null || true)"
export PIP_BREAK_SYSTEM_PACKAGES=1
export CC=clang
export CXX=clang++
EOF
    sudo chmod 755 "${hook_file}"
    sudo chown root:wheel "${hook_file}"
    log_info "Buildkite environment hook updated: ${hook_file}"
}

install_python_packages() {
    local python_bin
    python_bin="$(brew --prefix python@3.11)/bin/python3.11"
    "${python_bin}" -m pip install --break-system-packages --upgrade pip setuptools wheel packaging
    "${python_bin}" -m pip install --break-system-packages -r "${REPO_ROOT}/api/python/requirements.txt"
}

main() {
    check_macos
    check_xcode_cli
    check_brew

    log_step "Installing build tools"
    if [[ "${SKIP_BREW_UPDATE:-0}" != "1" ]]; then
        brew update
    fi

    brew_install git
    brew_install git-lfs
    brew_install wget
    brew_install coreutils
    brew_install pkg-config
    brew_install ccache
    brew_install cmake
    brew_install ninja
    brew_install protobuf
    brew_install go
    brew_install bazelisk
    brew_install python@3.11
    brew_install openjdk@17

    configure_bazel
    git lfs install >/dev/null 2>&1 || true
    install_python_packages
    write_environment_hook

    log_info "macOS build prerequisites are ready"
}

main "$@"
