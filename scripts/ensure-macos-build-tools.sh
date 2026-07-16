#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Install only the missing software prerequisites needed to build the macOS SDK
# with:
#   bash build.sh

set -euo pipefail

HOME="${HOME:-$(dscl . -read "/Users/$(id -un)" NFSHomeDirectory | awk '{print $2}')}"
export HOME
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON314_VERSION="${PYTHON314_VERSION:-3.14.6}"
PYTHON314_PREFIX="${PYTHON314_PREFIX:-${HOME}/.cache/openyuanrong/python/${PYTHON314_VERSION}}"

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

brew_install_if_missing() {
    local formula="$1"
    local check_cmd="$2"
    if command -v "${check_cmd}" >/dev/null 2>&1; then
        log_info "${check_cmd} already available"
        return
    fi
    brew_install "${formula}"
}

brew_mutate() {
    local brew_bin
    brew_bin="$(command -v brew)"
    if [[ "$(id -u)" == "0" ]]; then
        local brew_owner
        brew_owner="$(stat -f '%Su' "$(brew --prefix)")"
        if [[ -z "${brew_owner}" || "${brew_owner}" == "root" ]]; then
            log_error "Cannot determine the non-root Homebrew owner"
            exit 1
        fi
        sudo -H -u "${brew_owner}" env \
            HOMEBREW_NO_AUTO_UPDATE=1 \
            HOMEBREW_NO_ENV_HINTS=1 \
            "${brew_bin}" "$@"
        return
    fi
    "${brew_bin}" "$@"
}

brew_install() {
    local formula="$1"
    local installed_versions
    installed_versions="$(brew_mutate list --versions "$formula" 2>/dev/null || true)"
    if [[ -n "${installed_versions}" ]]; then
        log_info "$formula already installed: ${installed_versions}"
        return
    fi
    brew_mutate install "$formula"
}

python_formula_bin() {
    local formula="$1"
    if ! brew_mutate list --versions "$formula" >/dev/null 2>&1; then
        return 1
    fi
    local prefix
    prefix="$(brew_mutate --prefix "$formula")"
    case "$formula" in
        python@3.14) echo "${prefix}/bin/python3.14" ;;
        python@3.13) echo "${prefix}/bin/python3.13" ;;
        python@3.12) echo "${prefix}/bin/python3.12" ;;
        python@3.11) echo "${prefix}/bin/python3.11" ;;
        python@3.10) echo "${prefix}/bin/python3.10" ;;
        python@3.9) echo "${prefix}/bin/python3.9" ;;
        *) return 1 ;;
    esac
}

sdk_python_bin() {
    local py_version="$1"
    local py_minor="${py_version#python}"
    local py_env="py${py_minor//./}"
    local conda_root="${CONDA_PREFIX:-${HOME}/miniforge3}"
    local candidate

    for candidate in \
        "${PYTHON314_PREFIX}/bin/${py_version}" \
        "${py_version}" \
        "${conda_root}/bin/${py_version}" \
        "${conda_root}/envs/${py_env}/bin/${py_version}" \
        "${conda_root}/envs/yuanrong/bin/${py_version}" \
        "/opt/homebrew/opt/python@${py_minor}/bin/${py_version}" \
        "/usr/local/opt/python@${py_minor}/bin/${py_version}"; do
        if command -v "${candidate}" >/dev/null 2>&1; then
            command -v "${candidate}"
            return 0
        fi
        if [[ -x "${candidate}" ]]; then
            echo "${candidate}"
            return 0
        fi
    done
    if [[ -d "${conda_root}/envs" ]]; then
        candidate="$(find "${conda_root}/envs" -maxdepth 3 -type f -path "*/bin/${py_version}" 2>/dev/null | sort | head -1)"
        if [[ -n "${candidate}" && -x "${candidate}" ]]; then
            echo "${candidate}"
            return 0
        fi
    fi

    return 1
}

ensure_bazel() {
    if command -v bazel >/dev/null 2>&1; then
        log_info "bazel already available"
        return
    fi
    if command -v bazelisk >/dev/null 2>&1; then
        local brew_bin
        brew_bin="$(brew --prefix)/bin"
        ln -sf "$(command -v bazelisk)" "${brew_bin}/bazel"
        log_info "Linked bazel -> bazelisk"
        return
    fi
    brew_install bazelisk
    ensure_bazel
}

pick_python() {
    local py
    local candidates=()

    for py in python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
        if command -v "${py}" >/dev/null 2>&1; then
            candidates+=("$(command -v "${py}")")
        fi
    done

    for py in python@3.14 python@3.13 python@3.12 python@3.11 python@3.10 python@3.9; do
        if py_path="$(python_formula_bin "${py}" 2>/dev/null)"; then
            candidates+=("${py_path}")
        fi
    done

    for py in "${candidates[@]}"; do
        if [[ -x "${py}" ]] && "${py}" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
        then
            echo "${py}"
            return 0
        fi
    done

    return 1
}

pip_flags_for_python() {
    local python_bin="$1"
    if "${python_bin}" -m pip install --help 2>/dev/null | grep -q -- '--break-system-packages'; then
        echo "--break-system-packages"
    fi
}

ensure_python() {
    if pick_python >/dev/null 2>&1; then
        log_info "python3.9+ already available"
        return
    fi
    brew_install python@3.11
    brew_mutate link --overwrite --force python@3.11 >/dev/null 2>&1 || true

    if ! pick_python >/dev/null 2>&1; then
        log_error "python3.9+ is still unavailable after installing python@3.11"
        exit 1
    fi
}

ensure_python314() {
    local python_bin="${PYTHON314_PREFIX}/bin/python3.14"
    if [[ -x "${python_bin}" ]] && "${python_bin}" -c \
        'import platform, sys; assert platform.python_version() == sys.argv[1]' \
        "${PYTHON314_VERSION}" >/dev/null 2>&1; then
        log_info "Python ${PYTHON314_VERSION} already available at ${python_bin}"
        return
    fi

    brew_install openssl@3
    brew_install readline
    brew_install sqlite
    brew_install xz

    local openssl_prefix readline_prefix sqlite_prefix xz_prefix source_dir
    openssl_prefix="$(brew_mutate --prefix openssl@3)"
    readline_prefix="$(brew_mutate --prefix readline)"
    sqlite_prefix="$(brew_mutate --prefix sqlite)"
    xz_prefix="$(brew_mutate --prefix xz)"
    source_dir="$(mktemp -d)"

    log_step "Building exact Python ${PYTHON314_VERSION} for the macOS SDK"
    curl -fL \
        --retry 10 \
        --retry-delay 5 \
        --retry-all-errors \
        --continue-at - \
        --speed-limit 1024 \
        --speed-time 60 \
        "https://mirrors.huaweicloud.com/python/${PYTHON314_VERSION}/Python-${PYTHON314_VERSION}.tgz" \
        -o "${source_dir}/Python-${PYTHON314_VERSION}.tgz"
    tar -xzf "${source_dir}/Python-${PYTHON314_VERSION}.tgz" -C "${source_dir}"
    (
        cd "${source_dir}/Python-${PYTHON314_VERSION}"
        env \
            CPPFLAGS="-I${openssl_prefix}/include -I${readline_prefix}/include -I${sqlite_prefix}/include -I${xz_prefix}/include" \
            LDFLAGS="-L${openssl_prefix}/lib -L${readline_prefix}/lib -L${sqlite_prefix}/lib -L${xz_prefix}/lib" \
            PKG_CONFIG_PATH="${openssl_prefix}/lib/pkgconfig:${readline_prefix}/lib/pkgconfig:${sqlite_prefix}/lib/pkgconfig:${xz_prefix}/lib/pkgconfig" \
            ./configure --prefix="${PYTHON314_PREFIX}" --enable-shared --with-openssl="${openssl_prefix}"
        make -j"$(sysctl -n hw.logicalcpu)"
        make install
    )
    rm -rf "${source_dir}"
    "${python_bin}" -c \
        'import platform, sys; assert platform.python_version() == sys.argv[1]' \
        "${PYTHON314_VERSION}"
}

ensure_sdk_python_versions() {
    local py_version
    for py_version in ${SDK_PYTHON_VERSIONS:-python3.9 python3.10 python3.11 python3.12 python3.13 python3.14}; do
        if [[ "${py_version}" == "python3.14" ]]; then
            ensure_python314
            continue
        fi
        if sdk_python_bin "${py_version}" >/dev/null 2>&1; then
            log_info "${py_version} already available"
            continue
        fi
        brew_install "python@${py_version#python}"
    done
}

ensure_python_packages() {
    local python_bin
    python_bin="$(pick_python)"
    local pip_flag
    pip_flag="$(pip_flags_for_python "${python_bin}")"
    local missing
    missing="$("${python_bin}" - <<'PY'
import importlib.util
required = ["packaging", "wheel"]
missing = [name for name in required if importlib.util.find_spec(name) is None]
print(" ".join(missing))
PY
)"
    if [[ -z "${missing}" ]]; then
        log_info "python packages already available: packaging wheel"
        return
    fi
    "${python_bin}" -m pip install ${pip_flag:+$pip_flag} --upgrade ${missing}
}

main() {
    check_macos
    check_xcode_cli
    check_brew

    log_step "Checking minimal macOS SDK build prerequisites"
    if [[ "${SKIP_BREW_UPDATE:-0}" != "1" ]]; then
        brew_mutate update
    else
        export HOMEBREW_NO_AUTO_UPDATE="${HOMEBREW_NO_AUTO_UPDATE:-1}"
    fi

    brew_install_if_missing wget wget
    ensure_python
    ensure_sdk_python_versions
    brew_install_if_missing go go
    ensure_bazel

    ensure_python_packages

    log_info "macOS SDK build prerequisites are ready"
}

main "$@"
