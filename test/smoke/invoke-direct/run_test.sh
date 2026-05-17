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

# invoke_direct smoke test runner
# Installs openyuanrong whl, starts yr with frontend, runs SDK + HTTP tests.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
DEPLOY_PATH="${DEPLOY_PATH:-/tmp/yr-invoke-direct-smoke}"
STARTUP_LOG="${DEPLOY_PATH}/startup.log"
FAAS_HANDLER_DIR="${SCRIPT_DIR}/../minimal-python/faas"

# Fixed ports (avoid RANDOM port bug where frontend can't find metaservice)
FRONTEND_PORT="${FRONTEND_PORT:-18888}"
FRONTEND_GRPC_PORT="${FRONTEND_GRPC_PORT:-18889}"
META_SERVICE_PORT="${META_SERVICE_PORT:-18890}"
FUNCTION_AGENT_PORT="${FUNCTION_AGENT_PORT:-18891}"
FUNCTION_PROXY_PORT="${FUNCTION_PROXY_PORT:-18892}"
FUNCTION_PROXY_GRPC_PORT="${FUNCTION_PROXY_GRPC_PORT:-18893}"
GLOBAL_SCHEDULER_PORT="${GLOBAL_SCHEDULER_PORT:-18894}"
DS_MASTER_PORT="${DS_MASTER_PORT:-18895}"
DS_WORKER_PORT="${DS_WORKER_PORT:-18896}"
ETCD_PORT="${ETCD_PORT:-18897}"
ETCD_PEER_PORT="${ETCD_PEER_PORT:-18898}"

PYTHON_BIN="${PYTHON_BIN:-}"
YR_BIN="${YR_BIN:-}"
WHEEL_PATH=""
SDK_WHEEL_PATH=""
TEST_FAILED=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${YELLOW}[INFO]${NC} $1"; }
log_pass()  { echo -e "${GREEN}[PASS]${NC} $1"; }
log_fail()  { echo -e "${RED}[FAIL]${NC} $1"; TEST_FAILED=1; }

cleanup() {
    log_info "Cleaning up..."
    if [ -n "${YR_BIN}" ] && [ -x "${YR_BIN}" ]; then
        "${YR_BIN}" stop 2>/dev/null || true
    elif command -v yr >/dev/null 2>&1; then
        yr stop 2>/dev/null || true
    fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# resolve helpers
# ---------------------------------------------------------------------------

resolve_python() {
    if [ -n "${PYTHON_BIN}" ] && [ -x "${PYTHON_BIN}" ]; then
        return 0
    fi
    local candidate
    for candidate in \
        "${CONDA_PREFIX:-}/bin/python" \
        "${VIRTUAL_ENV:-}/bin/python" \
        /opt/buildtools/python3.11/bin/python3 \
        /opt/buildtools/python3.9/bin/python3 \
        "$(command -v python3.11 2>/dev/null || true)" \
        "$(command -v python3.9 2>/dev/null || true)" \
        "$(command -v python3 2>/dev/null || true)"; do
        if [ -n "${candidate}" ] && [ -x "${candidate}" ]; then
            PYTHON_BIN="${candidate}"
            return 0
        fi
    done
    log_fail "No usable Python interpreter found"
    exit 1
}

resolve_wheel() {
    local runtime_matches=()
    local sdk_matches=()
    mapfile -t runtime_matches < <(find "${PROJECT_ROOT}/output" -maxdepth 1 -type f -name 'openyuanrong-*.whl' | sort)
    mapfile -t sdk_matches < <(find "${PROJECT_ROOT}/output" -maxdepth 1 -type f -name 'openyuanrong_sdk-*.whl' | sort)
    if [ "${#runtime_matches[@]}" -eq 0 ]; then
        log_fail "No openyuanrong wheel found in output/"
        exit 1
    fi
    if [ "${#sdk_matches[@]}" -eq 0 ]; then
        log_fail "No openyuanrong_sdk wheel found in output/"
        exit 1
    fi
    WHEEL_PATH="${runtime_matches[0]}"
    SDK_WHEEL_PATH="${sdk_matches[0]}"
    log_pass "Wheels: $(basename "${WHEEL_PATH}"), $(basename "${SDK_WHEEL_PATH}")"
}

resolve_yr() {
    local bin_dir
    bin_dir="$(dirname "${PYTHON_BIN}")"
    if [ -x "${bin_dir}/yr" ]; then
        YR_BIN="${bin_dir}/yr"
        return 0
    fi
    if command -v yr >/dev/null 2>&1; then
        YR_BIN="$(command -v yr)"
        return 0
    fi
    log_fail "yr CLI not found after wheel installation"
    exit 1
}

resolve_runtime_host() {
    local host
    host="$(hostname -i 2>/dev/null | awk '{print $1}')" || true
    if [ -z "${host}" ]; then
        host="$("${PYTHON_BIN}" -c "import socket; print(socket.gethostbyname(socket.gethostname()))" 2>/dev/null)" || true
    fi
    if [ -z "${host}" ] || [[ "${host}" == 127.* ]]; then
        host="127.0.0.1"
    fi
    echo "${host}"
}

# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

install_wheel() {
    log_info "Installing wheels..."
    "${PYTHON_BIN}" -m pip uninstall openyuanrong openyuanrong_sdk -y >/dev/null 2>&1 || true
    "${PYTHON_BIN}" -m pip install --force-reinstall "${SDK_WHEEL_PATH}" "${WHEEL_PATH}" 2>&1 | tail -5
    resolve_yr
    log_pass "Installed"
}

# ---------------------------------------------------------------------------
# start / wait
# ---------------------------------------------------------------------------

start_runtime() {
    log_info "Starting yr with frontend..."
    mkdir -p "${DEPLOY_PATH}"

    "${YR_BIN}" stop 2>/dev/null || true
    sleep 1

    "${YR_BIN}" start --master \
        -d "${DEPLOY_PATH}" \
        --enable_faas_frontend=true \
        --enable_function_scheduler true \
        --enable_meta_service true \
        --enable_iam_server false \
        --enable_function_token_auth false \
        --port_policy FIX \
        --faas_frontend_http_port "${FRONTEND_PORT}" \
        --faas_frontend_grpc_port "${FRONTEND_GRPC_PORT}" \
        --meta_service_port "${META_SERVICE_PORT}" \
        --function_agent_port "${FUNCTION_AGENT_PORT}" \
        --function_proxy_port "${FUNCTION_PROXY_PORT}" \
        --function_proxy_grpc_port "${FUNCTION_PROXY_GRPC_PORT}" \
        --global_scheduler_port "${GLOBAL_SCHEDULER_PORT}" \
        --ds_master_port "${DS_MASTER_PORT}" \
        --ds_worker_port "${DS_WORKER_PORT}" \
        --etcd_port "${ETCD_PORT}" \
        --etcd_peer_port "${ETCD_PEER_PORT}" \
        -p "${SCRIPT_DIR}/services.yaml" \
        > "${STARTUP_LOG}" 2>&1

    log_pass "yr started (log: ${STARTUP_LOG})"
}

wait_ready() {
    local host="$1" port="$2"
    local url="https://${host}:${port}/healthz"
    log_info "Waiting for frontend readiness at ${url} ..."
    local max=60 i=0
    while [ "${i}" -lt "${max}" ]; do
        if curl -s -o /dev/null -w "%{http_code}" "${url}" 2>/dev/null | grep -q "200"; then
            log_pass "Frontend ready"
            return 0
        fi
        i=$((i + 1))
        sleep 2
    done
    log_fail "Frontend not ready after ${max} retries"
    tail -30 "${STARTUP_LOG}" 2>/dev/null || true
    exit 1
}

# ---------------------------------------------------------------------------
# run tests
# ---------------------------------------------------------------------------

run_tests() {
    local host="$1" frontend_port="$2"
    local server_addr="${host}:${frontend_port}"

    log_info "Running invoke_direct tests..."
    local output
    output=$(
        YR_SERVER_ADDRESS="${server_addr}" \
        YR_FRONTEND_ADDRESS="${server_addr}" \
        YR_FAAS_HANDLER_DIR="${FAAS_HANDLER_DIR}" \
        YR_TENANT_ID="0" \
        YR_NAMESPACE="faaspy" \
        YR_FUNCTION_NAME="invokedirecthandler" \
        "${PYTHON_BIN}" "${SCRIPT_DIR}/test_invoke_direct.py" 2>&1
    ) || {
        log_fail "test_invoke_direct.py exited with error"
        echo "${output}"
        exit 1
    }
    echo "${output}"

    if echo "${output}" | grep -q "invoke_direct Smoke: ALL PASS"; then
        log_pass "All invoke_direct tests passed"
    else
        log_fail "Some invoke_direct tests failed"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

main() {
    echo "=== invoke_direct Smoke Test ==="
    echo ""

    resolve_python
    log_info "Python: ${PYTHON_BIN}"

    resolve_wheel
    install_wheel
    start_runtime

    local host
    host="$(resolve_runtime_host)"

    log_info "Frontend endpoint: ${host}:${FRONTEND_PORT}"

    wait_ready "${host}" "${FRONTEND_PORT}"
    run_tests "${host}" "${FRONTEND_PORT}"

    echo ""
    echo "========================================"
    if [ "${TEST_FAILED}" -eq 0 ]; then
        echo -e "    ${GREEN}INVOKE_DIRECT SMOKE: PASS${NC}"
    else
        echo -e "    ${RED}INVOKE_DIRECT SMOKE: FAIL${NC}"
    fi
    echo "========================================"

    exit "${TEST_FAILED}"
}

main "$@"
