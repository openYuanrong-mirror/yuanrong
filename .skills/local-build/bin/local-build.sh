#!/usr/bin/env bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel 2>/dev/null || (cd "${SCRIPT_DIR}/../../.." && pwd))"
REPO_NAME="$(basename "${REPO_ROOT}")"
REPO_SAFE_NAME="$(printf '%s' "${REPO_NAME}" | tr -c '[:alnum:]-' '-')"

DRY_RUN=0
TARGET=""

DEFAULT_IMAGE="swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev/compile-ubuntu2004:v20260409_guaranteed"
LOCAL_IMAGE="${YR_LOCAL_BUILD_IMAGE:-${DEFAULT_IMAGE}}"
MAC_HOST="${YR_LOCAL_BUILD_MAC_HOST:-}"
X86_HOST="${YR_LOCAL_BUILD_X86_HOST:-}"

REMOTE_ROOT="/tmp/${REPO_SAFE_NAME}-local-build"
REMOTE_REPO_DIR="${REMOTE_ROOT}/repo"
WORKSPACE_DIR="/workspace"
ARTIFACT_ROOT="${REPO_ROOT}/output/local-build"
LOG_ROOT="${ARTIFACT_ROOT}/logs"
SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new)
CONTAINER_HOME_BASE="/tmp/yr-local-build-home"
CONTAINER_TMP_BASE="/tmp/yr-local-build-tmp"

usage() {
    cat <<'EOF'
用法:
  bash .skills/local-build/bin/local-build.sh [--dry-run] <target>

目标:
  linux-x86
  macos-sdk
  linux-arm
  all

示例:
  bash .skills/local-build/bin/local-build.sh linux-x86
  bash .skills/local-build/bin/local-build.sh macos-sdk
  bash .skills/local-build/bin/local-build.sh linux-arm
  bash .skills/local-build/bin/local-build.sh --dry-run all
EOF
}

join_by() {
    local delim="$1"
    shift
    local out=""
    local item
    for item in "$@"; do
        if [[ -z "${out}" ]]; then
            out="${item}"
        else
            out="${out}${delim}${item}"
        fi
    done
    printf '%s' "${out}"
}

log() {
    printf '[local-build] %s\n' "$*"
}

die() {
    printf '[local-build][error] %s\n' "$*" >&2
    exit 1
}

load_default_from_bashrc() {
    local target_var="$1"
    local export_name="$2"
    if [[ -n "${!target_var:-}" ]]; then
        return 0
    fi

    [[ -f "${HOME}/.bashrc" ]] || return 0

    local value
    value="$(
        sed -n -E "s/^[[:space:]]*export[[:space:]]+${export_name}=(.*)$/\\1/p" "${HOME}/.bashrc" | tail -n1
    )"
    value="${value%%#*}"
    value="$(printf '%s' "${value}" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"
    if [[ "${value}" =~ ^\".*\"$ || "${value}" =~ ^\'.*\'$ ]]; then
        value="${value:1:${#value}-2}"
    fi
    if [[ -n "${value}" ]]; then
        printf -v "${target_var}" '%s' "${value}"
    fi
}

setup_logging() {
    if [[ "${DRY_RUN}" -eq 1 || -n "${LOCAL_BUILD_LOG_ACTIVE:-}" ]]; then
        return 0
    fi

    mkdir -p "${LOG_ROOT}"

    local timestamp
    local log_file
    timestamp="$(date '+%Y%m%d-%H%M%S')"
    log_file="${LOG_ROOT}/${TARGET}-${timestamp}.log"

    export LOCAL_BUILD_LOG_ACTIVE=1
    export LOCAL_BUILD_LOG_FILE="${log_file}"
    exec > >(tee -a "${log_file}") 2>&1
    log "日志写入 ${log_file}"
}

run_cmd() {
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        printf '[dry-run] %s\n' "$*"
        return 0
    fi
    "$@"
}

run_bash() {
    local cmd="$1"
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        printf '[dry-run] bash -lc %q\n' "${cmd}"
        return 0
    fi
    bash -lc "${cmd}"
}

run_ssh_bash() {
    local host="$1"
    local cmd="$2"
    local escaped
    escaped="$(printf '%q' "${cmd}")"
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        printf '[dry-run] ssh %s bash -lc %s\n' "${host}" "${escaped}"
        return 0
    fi
    ssh "${SSH_OPTS[@]}" "${host}" "bash -lc ${escaped}"
}

require_command() {
    local cmd="$1"
    command -v "${cmd}" >/dev/null 2>&1 || die "缺少命令: ${cmd}"
}

require_env() {
    local name="$1"
    [[ -n "${!name:-}" ]] || die "缺少环境变量 ${name}，请设置后重试。"
}

is_linux_x86() {
    [[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" ]]
}

is_linux_arm() {
    [[ "$(uname -s)" == "Linux" && ("$(uname -m)" == "aarch64" || "$(uname -m)" == "arm64") ]]
}

is_macos() {
    [[ "$(uname -s)" == "Darwin" ]]
}

ensure_docker_local() {
    require_command docker
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        printf '[dry-run] docker info\n'
        return 0
    fi
    docker info >/dev/null 2>&1 || die "本机 Docker 不可用。"
}

ensure_docker_remote() {
    local host="$1"
    run_ssh_bash "${host}" "command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1" \
        || die "远端机器 ${host} 的 Docker 不可用。"
}

sync_repo_to_remote() {
    local host="$1"
    require_command rsync
    run_ssh_bash "${host}" "mkdir -p ${REMOTE_REPO_DIR}"
    local rsync_cmd=(
        rsync -az --delete
        --exclude=.git/
        --exclude=.omx/
        --exclude=.ccb/
        --exclude=.playwright-mcp/
        --exclude=thirdparty/
        --exclude=dist/
        --exclude=output/
        --exclude=build/
        --exclude='**/build/'
        --exclude='**/output/'
        --exclude='**/dist/'
        --exclude='bazel-*'
        --exclude='**/node_modules/'
        --exclude='test/st/cpp/build/'
        --exclude='test/st/deploy/'
        --exclude='metrics.tar.gz'
        "${REPO_ROOT}/"
        "${host}:${REMOTE_REPO_DIR}/"
    )
    run_cmd "${rsync_cmd[@]}"
}

local_container_name() {
    local target="$1"
    printf 'yr-local-build-%s-%s' "${REPO_SAFE_NAME}" "${target}"
}

prepare_local_container_user_env() {
    local target="$1"
    local uid="$2"
    local gid="$3"
    local name
    local home_dir="${CONTAINER_HOME_BASE}/${target}"
    local tmp_dir="${CONTAINER_TMP_BASE}/${target}"
    name="$(local_container_name "${target}")"

    run_cmd docker exec "${name}" bash -lc \
        "mkdir -p '${home_dir}' '${tmp_dir}' '${home_dir}/.cache' && chown -R ${uid}:${gid} '${home_dir}' '${tmp_dir}'"
}

prepare_remote_container_user_env() {
    local host="$1"
    local target="$2"
    local uid="$3"
    local gid="$4"
    local name
    local home_dir="${CONTAINER_HOME_BASE}/${target}"
    local tmp_dir="${CONTAINER_TMP_BASE}/${target}"
    name="$(local_container_name "${target}")"

    run_ssh_bash "${host}" \
        "docker exec ${name} bash -lc $(printf '%q' "mkdir -p '${home_dir}' '${tmp_dir}' '${home_dir}/.cache' && chown -R ${uid}:${gid} '${home_dir}' '${tmp_dir}'")"
}

ensure_local_container() {
    local target="$1"
    local platform="$2"
    local name
    name="$(local_container_name "${target}")"

    ensure_docker_local
    require_env LOCAL_IMAGE

    if [[ "${DRY_RUN}" -eq 1 ]]; then
        printf '[dry-run] ensure local container %s with image %s on %s\n' "${name}" "${LOCAL_IMAGE}" "${platform}"
        return 0
    fi

    local exists running image
    exists="$(docker ps -a --filter "name=^/${name}$" --format '{{.Names}}' || true)"
    if [[ -n "${exists}" ]]; then
        image="$(docker inspect -f '{{.Config.Image}}' "${name}")"
        if [[ "${image}" != "${LOCAL_IMAGE}" ]]; then
            run_cmd docker rm -f "${name}"
            exists=""
        fi
    fi

    if [[ -z "${exists}" ]]; then
        run_cmd docker run -d \
            --name "${name}" \
            --platform "${platform}" \
            -v "${REPO_ROOT}:${WORKSPACE_DIR}" \
            -w "${WORKSPACE_DIR}" \
            "${LOCAL_IMAGE}" \
            bash -lc 'while true; do sleep 3600; done' >/dev/null
        return 0
    fi

    running="$(docker inspect -f '{{.State.Running}}' "${name}")"
    if [[ "${running}" != "true" ]]; then
        run_cmd docker start "${name}" >/dev/null
    fi
}

ensure_remote_container() {
    local host="$1"
    local target="$2"
    local platform="$3"
    local name
    name="$(local_container_name "${target}")"

    ensure_docker_remote "${host}"
    require_env LOCAL_IMAGE

    run_ssh_bash "${host}" "
set -euo pipefail
name='${name}'
image='${LOCAL_IMAGE}'
repo='${REMOTE_REPO_DIR}'
platform='${platform}'
exists=\$(docker ps -a --filter \"name=^/\${name}\$\" --format '{{.Names}}' || true)
if [[ -n \"\${exists}\" ]]; then
  current_image=\$(docker inspect -f '{{.Config.Image}}' \"\${name}\")
  if [[ \"\${current_image}\" != \"\${image}\" ]]; then
    docker rm -f \"\${name}\" >/dev/null
    exists=''
  fi
fi
if [[ -z \"\${exists}\" ]]; then
  docker run -d \
    --name \"\${name}\" \
    --platform \"\${platform}\" \
    -v \"\${repo}:${WORKSPACE_DIR}\" \
    -w \"${WORKSPACE_DIR}\" \
    \"\${image}\" \
    bash -lc 'while true; do sleep 3600; done' >/dev/null
else
  running=\$(docker inspect -f '{{.State.Running}}' \"\${name}\")
  if [[ \"\${running}\" != \"true\" ]]; then
    docker start \"\${name}\" >/dev/null
  fi
fi
"
}

run_in_local_container() {
    local target="$1"
    local platform="$2"
    local cmd="$3"
    local name
    local uid
    local gid
    local home_dir="${CONTAINER_HOME_BASE}/${target}"
    local tmp_dir="${CONTAINER_TMP_BASE}/${target}"
    name="$(local_container_name "${target}")"
    ensure_local_container "${target}" "${platform}"
    uid="$(id -u)"
    gid="$(id -g)"

    if [[ "${DRY_RUN}" -eq 1 ]]; then
        printf '[dry-run] docker exec -i -u %s:%s -e HOME=%s -e TMPDIR=%s -e XDG_CACHE_HOME=%s/.cache %s bash -lc %s\n' \
            "${uid}" "${gid}" "${home_dir}" "${tmp_dir}" "${home_dir}" "${name}" "${cmd}"
        return 0
    fi

    prepare_local_container_user_env "${target}" "${uid}" "${gid}"
    run_cmd docker exec -i \
        -u "${uid}:${gid}" \
        -e HOME="${home_dir}" \
        -e TMPDIR="${tmp_dir}" \
        -e XDG_CACHE_HOME="${home_dir}/.cache" \
        "${name}" \
        bash -lc "${cmd}"
}

run_in_remote_container() {
    local host="$1"
    local target="$2"
    local platform="$3"
    local cmd="$4"
    local name
    local uid
    local gid
    local home_dir="${CONTAINER_HOME_BASE}/${target}"
    local tmp_dir="${CONTAINER_TMP_BASE}/${target}"
    name="$(local_container_name "${target}")"
    ensure_remote_container "${host}" "${target}" "${platform}"
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        printf '[dry-run] ssh %s docker exec -i -u <remote-uid>:<remote-gid> -e HOME=%s -e TMPDIR=%s -e XDG_CACHE_HOME=%s/.cache %s bash -lc %q\n' \
            "${host}" "${home_dir}" "${tmp_dir}" "${home_dir}" "${name}" "${cmd}"
        return 0
    fi

    uid="$(run_ssh_bash "${host}" "id -u")"
    gid="$(run_ssh_bash "${host}" "id -g")"
    prepare_remote_container_user_env "${host}" "${target}" "${uid}" "${gid}"
    run_ssh_bash "${host}" \
        "docker exec -i -u ${uid}:${gid} -e HOME='${home_dir}' -e TMPDIR='${tmp_dir}' -e XDG_CACHE_HOME='${home_dir}/.cache' ${name} bash -lc $(printf '%q' "${cmd}")"
}

collect_local_artifacts() {
    local target="$1"
    local target_dir="${ARTIFACT_ROOT}/${target}"
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        printf '[dry-run] collect local artifacts into %s\n' "${target_dir}"
        return 0
    fi
    mkdir -p "${target_dir}"
    find "${target_dir}" -maxdepth 1 -type f \( -name '*.tar.gz' -o -name '*.whl' \) -delete
    while IFS= read -r -d '' file; do
        cp -f "${file}" "${target_dir}/"
    done < <(find "${REPO_ROOT}/output" -maxdepth 1 -type f \( -name '*.tar.gz' -o -name '*.whl' \) -print0 2>/dev/null)
    log "产物已收集到 ${target_dir}"
    find "${target_dir}" -maxdepth 1 -type f | sort
}

collect_remote_artifacts() {
    local host="$1"
    local target="$2"
    local target_dir="${ARTIFACT_ROOT}/${target}"
    if [[ "${DRY_RUN}" -eq 1 ]]; then
        printf '[dry-run] collect remote artifacts from %s into %s\n' "${host}" "${target_dir}"
        return 0
    fi
    mkdir -p "${target_dir}"
    find "${target_dir}" -maxdepth 1 -type f \( -name '*.tar.gz' -o -name '*.whl' \) -delete
    local rsync_cmd=(
        rsync -az
        --prune-empty-dirs
        --include='*/'
        --include='*.tar.gz'
        --include='*.whl'
        --exclude='*'
        "${host}:${REMOTE_REPO_DIR}/output/"
        "${target_dir}/"
    )
    run_cmd "${rsync_cmd[@]}"
    log "远端产物已同步到 ${target_dir}"
    find "${target_dir}" -maxdepth 1 -type f | sort
}

macos_check_command() {
    cat <<'EOF'
if ! xcode-select -p >/dev/null 2>&1; then
  echo "missing_tool:Xcode Command Line Tools" >&2
  exit 1
fi
for cmd in clang clang++ go wget tar; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "missing_tool:${cmd}" >&2
    exit 1
  fi
done
if ! command -v bazel >/dev/null 2>&1 && ! command -v bazelisk >/dev/null 2>&1; then
  echo "missing_tool:bazel-or-bazelisk" >&2
  exit 1
fi
if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN=python3.11
elif command -v python3.10 >/dev/null 2>&1; then
  PYTHON_BIN=python3.10
elif command -v python3.9 >/dev/null 2>&1; then
  PYTHON_BIN=python3.9
else
  PYTHON_BIN=python3
fi
"${PYTHON_BIN}" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
EOF
}

macos_python_prepare_command() {
    cat <<'EOF'
if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN=python3.11
elif command -v python3.10 >/dev/null 2>&1; then
  PYTHON_BIN=python3.10
elif command -v python3.9 >/dev/null 2>&1; then
  PYTHON_BIN=python3.9
else
  PYTHON_BIN=python3
fi
MISSING_PACKAGES=$("${PYTHON_BIN}" - <<'PY'
import importlib.util
required = ["packaging", "wheel"]
missing = [name for name in required if importlib.util.find_spec(name) is None]
print(" ".join(missing))
PY
)
if [[ -n "${MISSING_PACKAGES}" ]]; then
  "${PYTHON_BIN}" -m pip install --break-system-packages --upgrade ${MISSING_PACKAGES}
fi
EOF
}

linux_build_command() {
    cat <<'EOF'
set -euo pipefail
cd /workspace
export CCACHE_DISABLE=1
export PATH=/opt/buildtools/python3.11/bin:/opt/buildtools/python3.10/bin:/opt/buildtools/python3.9/bin:$PATH
EOF
    cat <<'EOF'
rm -f output/*.tar.gz output/*.whl
bazel shutdown >/dev/null 2>&1 || true
make all
EOF
}

macos_sdk_build_command() {
    local repo_dir="$1"
    local tool_check
    local python_prepare
    tool_check="$(macos_check_command)"
    python_prepare="$(macos_python_prepare_command)"
    cat <<EOF
set -euo pipefail
${tool_check}
cd ${repo_dir}
export CCACHE_DISABLE=1
export SKIP_BREW_UPDATE="\${SKIP_BREW_UPDATE:-1}"
${python_prepare}
rm -f output/openyuanrong-*.whl output/openyuanrong_sdk-*.whl
bash scripts/ensure-macos-build-tools.sh
bazel shutdown >/dev/null 2>&1 || true
bash build.sh
EOF
}

build_linux_x86() {
    local cmd
    cmd="$(linux_build_command)"
    if is_linux_x86; then
        log "检测到当前机器是 x86_64 Linux，使用本地镜像容器构建 linux-x86。"
        run_in_local_container "linux-x86" "linux/amd64" "${cmd}"
        collect_local_artifacts "linux-x86"
        return 0
    fi

    if [[ -n "${X86_HOST}" ]]; then
        log "当前机器不是 x86_64 Linux，切换到远端 ${X86_HOST} 构建 linux-x86。"
        sync_repo_to_remote "${X86_HOST}"
        run_in_remote_container "${X86_HOST}" "linux-x86" "linux/amd64" "${cmd}"
        collect_remote_artifacts "${X86_HOST}" "linux-x86"
        return 0
    fi

    die "当前机器不是 x86_64 Linux，且未配置 YR_LOCAL_BUILD_X86_HOST。请提供 x86 构建环境后重试。"
}

build_linux_arm() {
    local cmd
    cmd="$(linux_build_command)"
    if is_linux_arm; then
        log "检测到当前机器是 ARM Linux，使用本地镜像容器构建 linux-arm。"
        run_in_local_container "linux-arm" "linux/arm64" "${cmd}"
        collect_local_artifacts "linux-arm"
        return 0
    fi

    [[ -n "${MAC_HOST}" ]] || die "当前机器不是 ARM Linux，且未配置 YR_LOCAL_BUILD_MAC_HOST。请提供 ARM 构建环境后重试。"
    log "当前机器不是 ARM Linux，切换到远端 ${MAC_HOST} 构建 linux-arm。"
    sync_repo_to_remote "${MAC_HOST}"
    run_in_remote_container "${MAC_HOST}" "linux-arm" "linux/arm64" "${cmd}"
    collect_remote_artifacts "${MAC_HOST}" "linux-arm"
}

build_macos_sdk() {
    local cmd
    if is_macos; then
        log "检测到当前机器是 macOS，直接构建 macOS SDK。"
        cmd="$(macos_sdk_build_command "${REPO_ROOT}")"
        run_bash "${cmd}"
        collect_local_artifacts "macos-sdk"
        return 0
    fi

    [[ -n "${MAC_HOST}" ]] || die "当前机器不是 macOS，且未配置 YR_LOCAL_BUILD_MAC_HOST。请提供 macOS 构建环境后重试。"
    log "当前机器不是 macOS，切换到远端 ${MAC_HOST} 构建 macOS SDK。"
    sync_repo_to_remote "${MAC_HOST}"
    cmd="$(macos_sdk_build_command "${REMOTE_REPO_DIR}")"
    run_ssh_bash "${MAC_HOST}" "${cmd}"
    collect_remote_artifacts "${MAC_HOST}" "macos-sdk"
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run)
                DRY_RUN=1
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            linux-x86|macos-sdk|linux-arm|all)
                TARGET="$1"
                shift
                ;;
            *)
                die "未知参数: $1"
                ;;
        esac
    done

    [[ -n "${TARGET}" ]] || {
        usage
        exit 1
    }
}

prepare() {
    load_default_from_bashrc MAC_HOST YR_LOCAL_BUILD_MAC_HOST
    load_default_from_bashrc X86_HOST YR_LOCAL_BUILD_X86_HOST
    setup_logging
    if [[ "${DRY_RUN}" -eq 0 ]]; then
        mkdir -p "${ARTIFACT_ROOT}"
    fi
}

main() {
    parse_args "$@"
    prepare

    case "${TARGET}" in
        linux-x86)
            build_linux_x86
            ;;
        macos-sdk)
            build_macos_sdk
            ;;
        linux-arm)
            build_linux_arm
            ;;
        all)
            build_linux_x86
            build_macos_sdk
            build_linux_arm
            ;;
    esac
}

main "$@"
