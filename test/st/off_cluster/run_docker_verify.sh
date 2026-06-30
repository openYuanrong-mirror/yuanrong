#!/usr/bin/env bash
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
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
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

COMPILE_CONTAINER="${COMPILE_CONTAINER:-compile}"
REPO_ROOT_IN_CONTAINER="${REPO_ROOT_IN_CONTAINER:-${REPO_ROOT}}"
AIO_CONTAINER_NAME="${AIO_CONTAINER_NAME:-aio-yr}"
AIO_PORT="${AIO_PORT:-38888}"
PYTHON_BIN="${PYTHON_BIN:-python3.10}"
RUNTIME_PYTHON="${RUNTIME_PYTHON:-${PYTHON_BIN}}"
USE_UV_VENV="${YRCLI_VERIFY_USE_UV_VENV:-true}"
VERIFY_VENV="${YRCLI_VERIFY_VENV:-/tmp/yrcli-sandbox-verify-venv}"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 8)}"
FUNCTIONSYSTEM_JOBS="${FUNCTIONSYSTEM_JOBS:-8}"
COMPILE_USER_SPEC="${COMPILE_USER_SPEC:-$(stat -c '%u:%g' "${REPO_ROOT}")}"
if command -v sha256sum >/dev/null 2>&1; then
    REPO_CACHE_SUFFIX="$(printf '%s' "${REPO_ROOT_IN_CONTAINER}" | sha256sum | cut -c1-16)"
else
    REPO_CACHE_SUFFIX="$(basename "${REPO_ROOT_IN_CONTAINER}")"
fi
FUNCTIONSYSTEM_VENDOR_CACHE_DIR="${FUNCTIONSYSTEM_VENDOR_CACHE_DIR:-/tmp/functionsystem-vendor-cache-${REPO_CACHE_SUFFIX}}"
SKIP_COMPILE=0
SKIP_IMAGE=0
SKIP_START=0
SKIP_CLEAN=0
PYTEST_ARGS=()

usage() {
    cat <<EOF
Usage: $0 [options] [-- pytest-args...]

Build and verify yrcli sandbox access paths against the local Docker AIO deployment.

Default flow:
  1. docker exec <compile> build all artifacts with ${RUNTIME_PYTHON}
  2. make image on the host Docker engine
  3. start deploy/sandbox/docker/docker-compose.yml
  4. run off-cluster yrcli image/port-forward/tunnel verification

Options:
  --compile-container NAME     Compile container name (default: ${COMPILE_CONTAINER})
  --repo-root-in-container DIR Repo path inside compile container (default: host repo path)
  --aio-container-name NAME    AIO container name (default: ${AIO_CONTAINER_NAME})
  --aio-port PORT              Host port for AIO HTTP endpoint (default: ${AIO_PORT})
  --python-bin PATH            Base Python used to create the uv verification venv
                               (default: ${PYTHON_BIN}; with --no-uv-venv, used directly)
  --runtime-python PATH        Python runtime used for runtime/openyuanrong wheels
                               (default: ${RUNTIME_PYTHON})
  --verify-venv DIR            uv verification venv path (default: ${VERIFY_VENV})
  --jobs N                     build JOBS value (default: ${JOBS})
  --functionsystem-jobs N      FUNCTIONSYSTEM_JOBS value (default: ${FUNCTIONSYSTEM_JOBS})
  --functionsystem-cache-dir D FS_VENDOR_CACHE_DIR used during compile
                               (default: ${FUNCTIONSYSTEM_VENDOR_CACHE_DIR})
  --compile-user UID:GID       User used for make all inside compile container
                               (default: repo owner ${COMPILE_USER_SPEC})
  --skip-compile               Skip make all in compile container
  --skip-image                 Skip host make image
  --skip-start                 Skip docker compose start
  --skip-clean                 Skip generated function system vendor cleanup before compile
  --no-uv-venv                 Use --python-bin directly instead of installing output wheels into uv venv
  -h, --help                   Show this help

Useful environment:
  YR_SANDBOX_VERIFY_IMAGE      Image passed to yrcli sandbox create --image
                               (default: aio-yr-runtime:latest)
  YRCLI_SANDBOX_CREATE_TIMEOUT Sandbox create timeout seconds (default: 600)

Examples:
  $0
  $0 --skip-compile --skip-image --skip-start -- -k port_forwarding
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --compile-container)
            COMPILE_CONTAINER="$2"; shift 2 ;;
        --repo-root-in-container)
            REPO_ROOT_IN_CONTAINER="$2"; shift 2 ;;
        --aio-container-name)
            AIO_CONTAINER_NAME="$2"; shift 2 ;;
        --aio-port)
            AIO_PORT="$2"; shift 2 ;;
        --python-bin)
            PYTHON_BIN="$2"; shift 2 ;;
        --runtime-python)
            RUNTIME_PYTHON="$2"; shift 2 ;;
        --verify-venv)
            VERIFY_VENV="$2"; shift 2 ;;
        --jobs)
            JOBS="$2"; shift 2 ;;
        --functionsystem-jobs)
            FUNCTIONSYSTEM_JOBS="$2"; shift 2 ;;
        --functionsystem-cache-dir)
            FUNCTIONSYSTEM_VENDOR_CACHE_DIR="$2"; shift 2 ;;
        --compile-user)
            COMPILE_USER_SPEC="$2"; shift 2 ;;
        --skip-compile)
            SKIP_COMPILE=1; shift ;;
        --skip-image)
            SKIP_IMAGE=1; shift ;;
        --skip-start)
            SKIP_START=1; shift ;;
        --skip-clean)
            SKIP_CLEAN=1; shift ;;
        --no-uv-venv)
            USE_UV_VENV=false; shift ;;
        -h|--help)
            usage; exit 0 ;;
        --)
            shift
            PYTEST_ARGS=("$@")
            break ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            exit 1 ;;
    esac
done

log_step() {
    printf '\n==> %s\n' "$*"
}

is_enabled() {
    case "$1" in
        1|true|TRUE|yes|YES|on|ON) return 0 ;;
        *) return 1 ;;
    esac
}

resolve_single_file() {
    local pattern="$1"
    local matches=()

    mapfile -t matches < <(compgen -G "${pattern}" | sort -V)
    if [ "${#matches[@]}" -eq 0 ]; then
        echo "Missing required artifact matching ${pattern}" >&2
        return 1
    fi
    if [ "${#matches[@]}" -ne 1 ]; then
        echo "Expected exactly one artifact matching ${pattern}, found ${#matches[@]}" >&2
        printf '%s\n' "${matches[@]}" >&2
        return 1
    fi

    printf '%s\n' "${matches[0]}"
}

prepare_verify_venv() {
    local base_python="$1"
    local sdk_wheel
    local runtime_wheel

    if ! command -v uv >/dev/null 2>&1; then
        echo "uv is required for the default verification venv. Install uv or pass --no-uv-venv." >&2
        exit 1
    fi

    sdk_wheel="$(resolve_single_file "${REPO_ROOT}/output/openyuanrong_sdk*.whl")"
    runtime_wheel="$(resolve_single_file "${REPO_ROOT}/output/openyuanrong-*.whl")"

    log_step "Prepare uv verification venv ${VERIFY_VENV}"
    rm -rf "${VERIFY_VENV}"
    uv venv --python "${base_python}" "${VERIFY_VENV}"
    uv pip install --python "${VERIFY_VENV}/bin/python" \
        --no-cache \
        "${sdk_wheel}" \
        "${runtime_wheel}" \
        pytest

    PYTHON_BIN="${VERIFY_VENV}/bin/python"
}

if [[ "${SKIP_COMPILE}" -eq 0 ]]; then
    if ! docker inspect "${COMPILE_CONTAINER}" >/dev/null 2>&1; then
        echo "Compile container not found: ${COMPILE_CONTAINER}" >&2
        exit 1
    fi
fi

if [[ "${SKIP_COMPILE}" -eq 0 ]]; then
    log_step "Normalize generated output ownership in container ${COMPILE_CONTAINER}"
    docker exec "${COMPILE_CONTAINER}" bash -lc \
        "cd '${REPO_ROOT_IN_CONTAINER}' && \
         chown -R '${COMPILE_USER_SPEC}' build output metrics frontend/build/_output frontend/output frontend/pkg/common/faas_common/grpc datasystem/build datasystem/output functionsystem/vendor/build functionsystem/vendor/output functionsystem/vendor/src functionsystem/output functionsystem/functionsystem/build functionsystem/functionsystem/output functionsystem/functionsystem/src/common/proto/pb/posix functionsystem/functionsystem/src/common/utils/version.h functionsystem/functionsystem/apps/cli/internal/pb functionsystem/functionsystem/apps/meta_service/function_repo functionsystem/runtime-launcher/api/proto/runtime/v1 functionsystem/runtime-launcher/bin functionsystem/common/logs/build functionsystem/common/logs/output functionsystem/common/litebus/build functionsystem/common/litebus/output functionsystem/common/metrics/build functionsystem/common/metrics/output go/build go/bin go/output go/pkg '${FUNCTIONSYSTEM_VENDOR_CACHE_DIR}' 2>/dev/null || true"

    log_step "Configure git safe.directory in container ${COMPILE_CONTAINER}"
    docker exec -u "${COMPILE_USER_SPEC}" -e HOME=/home/wyc "${COMPILE_CONTAINER}" bash -lc \
        "git config --global --add safe.directory '${REPO_ROOT_IN_CONTAINER}' && \
         git config --global --add safe.directory '${REPO_ROOT_IN_CONTAINER}/datasystem' && \
         git config --global --add safe.directory '${REPO_ROOT_IN_CONTAINER}/functionsystem' && \
         git config --global --add safe.directory '${REPO_ROOT_IN_CONTAINER}/frontend'"
fi

if [[ "${SKIP_COMPILE}" -eq 0 && "${SKIP_CLEAN}" -eq 0 ]]; then
    log_step "Clean stale function system build caches in container ${COMPILE_CONTAINER}"
    docker exec -u "${COMPILE_USER_SPEC}" -e HOME=/home/wyc "${COMPILE_CONTAINER}" bash -lc \
        "cd '${REPO_ROOT_IN_CONTAINER}/functionsystem' && bash run.sh clean --skip_vendor ''"
fi

if [[ "${SKIP_COMPILE}" -eq 0 ]]; then
    log_step "Remove stale Python wheel artifacts in container ${COMPILE_CONTAINER}"
    docker exec "${COMPILE_CONTAINER}" bash -lc \
        "cd '${REPO_ROOT_IN_CONTAINER}' && rm -f output/openyuanrong*.whl api/python/dist/*.whl"

    log_step "Compile artifacts in container ${COMPILE_CONTAINER}"
    docker exec -u "${COMPILE_USER_SPEC}" -e HOME=/home/wyc "${COMPILE_CONTAINER}" bash -lc \
        "cd '${REPO_ROOT_IN_CONTAINER}' && \
         FS_VENDOR_CACHE_DIR='${FUNCTIONSYSTEM_VENDOR_CACHE_DIR}' make frontend datasystem functionsystem runtime_launcher dashboard JOBS='${JOBS}' FUNCTIONSYSTEM_JOBS='${FUNCTIONSYSTEM_JOBS}' && \
         bash build.sh -P -p '${RUNTIME_PYTHON}' -j '${JOBS}'"
fi

if [[ "${SKIP_IMAGE}" -eq 0 ]]; then
    log_step "Build Docker AIO images on host"
    make -C "${REPO_ROOT}" image
fi

if [[ "${SKIP_START}" -eq 0 ]]; then
    log_step "Start Docker AIO deployment"
    AIO_CONTAINER_NAME="${AIO_CONTAINER_NAME}" \
    AIO_PORT="${AIO_PORT}" \
    bash "${REPO_ROOT}/deploy/sandbox/docker/run.sh"
fi

log_step "Wait for Docker AIO endpoint"
for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${AIO_PORT}/" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

if ! curl -fsS "http://127.0.0.1:${AIO_PORT}/" >/dev/null 2>&1; then
    echo "AIO endpoint is not reachable: http://127.0.0.1:${AIO_PORT}/" >&2
    docker logs --tail 200 "${AIO_CONTAINER_NAME}" >&2 || true
    exit 1
fi

if is_enabled "${USE_UV_VENV}"; then
    prepare_verify_venv "${PYTHON_BIN}"
fi

log_step "Run yrcli sandbox access-path verification"
export YR_SERVER_ADDRESS="127.0.0.1:${AIO_PORT}"
export YR_GATEWAY_ADDRESS="${YR_GATEWAY_ADDRESS:-127.0.0.1:${AIO_PORT}}"
export YR_ENABLE_TLS="false"
export YR_IN_CLUSTER="false"
export YR_SANDBOX_VERIFY_IMAGE="${YR_SANDBOX_VERIFY_IMAGE:-aio-yr-runtime:latest}"
export YRCLI_VERIFY_PYTHON_BIN="${PYTHON_BIN}"

"${PYTHON_BIN}" -m pytest -s -vv \
    "${REPO_ROOT}/test/st/off_cluster/test_yrcli_sandbox_access_paths.py" \
    "${PYTEST_ARGS[@]}"

log_step "Verification passed"
