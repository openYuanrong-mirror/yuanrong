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

# Unset proxy vars so curl reaches local cluster addresses directly
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
DEPLOY_PATH="${DEPLOY_PATH:-/tmp/yr-minimal-python-smoke}"
STARTUP_LOG="${DEPLOY_PATH}/startup.log"

FRONTEND_PORT="${FRONTEND_PORT:-8888}"
FRONTEND_GRPC_PORT="${FRONTEND_GRPC_PORT:-31223}"
META_SERVICE_PORT="${META_SERVICE_PORT:-31111}"
IAM_SERVER_PORT="${IAM_SERVER_PORT:-31112}"
FUNCTION_AGENT_PORT="${FUNCTION_AGENT_PORT:-58866}"
FUNCTION_PROXY_PORT="${FUNCTION_PROXY_PORT:-22772}"
FUNCTION_PROXY_GRPC_PORT="${FUNCTION_PROXY_GRPC_PORT:-22773}"
GLOBAL_SCHEDULER_PORT="${GLOBAL_SCHEDULER_PORT:-22770}"
DS_MASTER_PORT="${DS_MASTER_PORT:-12123}"
DS_WORKER_PORT="${DS_WORKER_PORT:-31501}"
ETCD_PORT="${ETCD_PORT:-32379}"
ETCD_PEER_PORT="${ETCD_PEER_PORT:-32380}"

SMOKE_SERVER_ADDRESS="127.0.0.1:${FRONTEND_PORT}"
RUNTIME_HOST="${RUNTIME_HOST:-}"
SMOKE_BASE_URL=""

PYTHON_BIN="${PYTHON_BIN:-}"
YR_BIN="${YR_BIN:-}"
WHEEL_PATH=""
SDK_WHEEL_PATH=""
SMOKE_FAILED=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    SMOKE_FAILED=1
}

print_diagnostics() {
    echo ""
    echo "=== Diagnostics ==="
    echo "Failing stage: $1"
    echo ""
    echo "--- Process snapshot ---"
    ps aux | grep -E '(yr|function|scheduler|frontend|etcd)' | grep -v grep || echo "No yr processes found"
    echo ""
    echo "--- Port status ---"
    if command -v ss >/dev/null 2>&1; then
        ss -ltnp 2>/dev/null | grep -E "(:${FRONTEND_PORT}|:${FRONTEND_GRPC_PORT}|:${META_SERVICE_PORT}|:${IAM_SERVER_PORT}|:${FUNCTION_AGENT_PORT}|:${FUNCTION_PROXY_PORT}|:${FUNCTION_PROXY_GRPC_PORT}|:${GLOBAL_SCHEDULER_PORT}|:${DS_MASTER_PORT}|:${DS_WORKER_PORT}|:${ETCD_PORT}|:${ETCD_PEER_PORT})" || echo "Ports not listening"
    else
        netstat -ltnp 2>/dev/null | grep -E "(:${FRONTEND_PORT}|:${FRONTEND_GRPC_PORT}|:${META_SERVICE_PORT}|:${IAM_SERVER_PORT}|:${FUNCTION_AGENT_PORT}|:${FUNCTION_PROXY_PORT}|:${FUNCTION_PROXY_GRPC_PORT}|:${GLOBAL_SCHEDULER_PORT}|:${DS_MASTER_PORT}|:${DS_WORKER_PORT}|:${ETCD_PORT}|:${ETCD_PEER_PORT})" || echo "Ports not listening"
    fi
    echo ""
    echo "--- Startup log tail ---"
    tail -30 "${STARTUP_LOG}" 2>/dev/null || echo "No startup log found"
    echo ""
}

cleanup() {
    log_info "Cleaning up..."
    if [ -n "${YR_BIN}" ] && [ -x "${YR_BIN}" ]; then
        "${YR_BIN}" stop 2>/dev/null || true
    elif command -v yr >/dev/null 2>&1; then
        yr stop 2>/dev/null || true
    fi
}
trap cleanup EXIT

check_dev_container() {
    if [ ! -f "/.dockerenv" ]; then
        log_fail "This smoke flow is intended to run inside the dev container"
        echo "Run: docker exec dev bash -lc 'cd ${PROJECT_ROOT}/example/minimal-python && ./run_smoke.sh'"
        exit 1
    fi
}

resolve_runtime_host() {
    if [ -n "${RUNTIME_HOST}" ]; then
        SMOKE_SERVER_ADDRESS="${RUNTIME_HOST}:${FRONTEND_PORT}"
        SMOKE_BASE_URL="http://${RUNTIME_HOST}:${FRONTEND_PORT}"
        return 0
    fi

    RUNTIME_HOST="$(
        {
            hostname -i 2>/dev/null || true
        } | awk '{print $1}'
    )"
    if [ -z "${RUNTIME_HOST}" ]; then
        RUNTIME_HOST="$("${PYTHON_BIN}" - <<'PY'
import socket

host = "127.0.0.1"
try:
    value = socket.gethostbyname(socket.gethostname())
    if value and not value.startswith("127."):
        host = value
except Exception:
    pass
print(host)
PY
)"
    fi
    SMOKE_SERVER_ADDRESS="${RUNTIME_HOST}:${FRONTEND_PORT}"
    SMOKE_BASE_URL="http://${RUNTIME_HOST}:${FRONTEND_PORT}"
}

resolve_python() {
    if [ -n "${PYTHON_BIN}" ] && [ -x "${PYTHON_BIN}" ]; then
        return 0
    fi

    local candidate
    for candidate in \
        "${CONDA_PREFIX:-}/bin/python" \
        "${VIRTUAL_ENV:-}/bin/python" \
        /opt/buildtools/python3.9/bin/python3 \
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
        log_fail "No wheel found in output/. Build required."
        echo "Run: make functionsystem"
        exit 1
    fi
    if [ "${#sdk_matches[@]}" -eq 0 ]; then
        log_fail "No openyuanrong_sdk wheel found in output/. Build required."
        echo "Run: make functionsystem"
        exit 1
    fi
    if [ "${#runtime_matches[@]}" -ne 1 ]; then
        log_fail "Expected exactly one openyuanrong wheel, found ${#runtime_matches[@]}"
        printf '%s\n' "${runtime_matches[@]}"
        exit 1
    fi
    if [ "${#sdk_matches[@]}" -ne 1 ]; then
        log_fail "Expected exactly one openyuanrong_sdk wheel, found ${#sdk_matches[@]}"
        printf '%s\n' "${sdk_matches[@]}"
        exit 1
    fi
    WHEEL_PATH="${runtime_matches[0]}"
    SDK_WHEEL_PATH="${sdk_matches[0]}"
    log_pass "Wheel found: $(basename "${WHEEL_PATH}")"
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

stop_runtime_if_present() {
    if [ -n "${YR_BIN}" ] && [ -x "${YR_BIN}" ]; then
        log_info "Stopping existing runtime in current environment..."
        "${YR_BIN}" stop 2>/dev/null || true
        sleep 2
        log_pass "Stopped"
    else
        log_info "Skipping pre-stop because yr CLI is not installed yet"
    fi
}

install_wheel() {
    log_info "Installing wheel..."
    "${PYTHON_BIN}" -m pip uninstall openyuanrong openyuanrong_sdk -y >/dev/null 2>&1 || true
    "${PYTHON_BIN}" -m pip install --force-reinstall "${SDK_WHEEL_PATH}" "${WHEEL_PATH}" 2>&1 | tail -20
    resolve_yr
    log_pass "Installed"
}

check_ports() {
    local ports=(
        "${FRONTEND_PORT}"
        "${FRONTEND_GRPC_PORT}"
        "${META_SERVICE_PORT}"
        "${IAM_SERVER_PORT}"
        "${FUNCTION_AGENT_PORT}"
        "${FUNCTION_PROXY_PORT}"
        "${FUNCTION_PROXY_GRPC_PORT}"
        "${GLOBAL_SCHEDULER_PORT}"
        "${DS_MASTER_PORT}"
        "${DS_WORKER_PORT}"
        "${ETCD_PORT}"
        "${ETCD_PEER_PORT}"
    )
    local port
    log_info "Checking required ports..."
    for port in "${ports[@]}"; do
        if (command -v ss >/dev/null 2>&1 && ss -ltnp 2>/dev/null | grep -q ":${port} ") || \
           (command -v netstat >/dev/null 2>&1 && netstat -ltnp 2>/dev/null | grep -q ":${port} "); then
            log_fail "Port ${port} already in use"
            if command -v ss >/dev/null 2>&1; then
                ss -ltnp 2>/dev/null | grep -E ":${port} " || true
            else
                netstat -ltnp 2>/dev/null | grep -E ":${port} " || true
            fi
            echo "Override ports with env vars, for example: FRONTEND_PORT=18888 ./run_smoke.sh"
            exit 1
        fi
    done
    log_pass "Ports free"
}

start_runtime() {
    log_info "Starting runtime..."
    export LITEBUS_DATA_KEY=6D792D7365637265742D6B65792D666F722D6A77742D64656D6F
    mkdir -p "${DEPLOY_PATH}"

    "${YR_BIN}" stop 2>/dev/null || true
    sleep 1

    "${YR_BIN}" start --master \
        -d "${DEPLOY_PATH}" \
        --runtime_home_dir "${HOME}" \
        --enable_faas_frontend=true \
        -l DEBUG \
        --port_policy FIX \
        --enable_function_scheduler true \
        --enable_meta_service true \
        --enable_iam_server false \
        --enable_function_token_auth false \
        --faas_frontend_http_port "${FRONTEND_PORT}" \
        --faas_frontend_grpc_port "${FRONTEND_GRPC_PORT}" \
        --meta_service_port "${META_SERVICE_PORT}" \
        --iam_server_port "${IAM_SERVER_PORT}" \
        --function_agent_port "${FUNCTION_AGENT_PORT}" \
        --function_proxy_port "${FUNCTION_PROXY_PORT}" \
        --function_proxy_grpc_port "${FUNCTION_PROXY_GRPC_PORT}" \
        --global_scheduler_port "${GLOBAL_SCHEDULER_PORT}" \
        --ds_master_port "${DS_MASTER_PORT}" \
        --ds_worker_port "${DS_WORKER_PORT}" \
        --etcd_port "${ETCD_PORT}" \
        --etcd_peer_port "${ETCD_PEER_PORT}" \
        -p "${SCRIPT_DIR}/services.yaml" \
        > "${STARTUP_LOG}" 2>&1 &

    log_pass "Started (log: ${STARTUP_LOG})"
}

wait_ready() {
    log_info "Waiting for runtime readiness..."
    local max_retries=60
    local retry=0
    while [ "${retry}" -lt "${max_retries}" ]; do
        if curl -s -o /dev/null -w "%{http_code}" "${SMOKE_BASE_URL}/healthz" 2>/dev/null | grep -q "200"; then
            log_pass "Runtime ready"
            return 0
        fi
        retry=$((retry + 1))
        sleep 2
    done
    log_fail "Runtime not ready after ${max_retries} retries"
    print_diagnostics "wait_ready"
    exit 1
}

run_sdk_smoke() {
    log_info "Running SDK smoke..."
    local output
    output=$(
        YR_SMOKE_SERVER_ADDRESS="${SMOKE_SERVER_ADDRESS}" \
        "${PYTHON_BIN}" "${SCRIPT_DIR}/sdk_smoke.py" 2>&1
    ) || {
        log_fail "SDK smoke failed"
        echo "${output}"
        print_diagnostics "sdk_smoke"
        exit 1
    }
    echo "${output}"
    if echo "${output}" | grep -q "SDK Smoke: ALL PASS"; then
        log_pass "SDK smoke passed"
        return 0
    fi
    log_fail "SDK smoke failed"
    print_diagnostics "sdk_smoke"
    exit 1
}

run_faas_smoke() {
    log_info "Running FaaS smoke..."
    local output
    output=$(
        YR_SMOKE_BASE_URL="${SMOKE_BASE_URL}" \
        YR_SMOKE_TENANT="0" \
        YR_SMOKE_NAMESPACE="faaspy" \
        YR_SMOKE_FUNCTION="smokehandler" \
        bash "${SCRIPT_DIR}/faas_smoke.sh" 2>&1
    ) || {
        log_fail "FaaS smoke failed"
        echo "${output}"
        print_diagnostics "faas_smoke"
        exit 1
    }
    echo "${output}"
    if echo "${output}" | grep -q "FaaS Smoke: ALL PASS"; then
        log_pass "FaaS smoke passed"
        return 0
    fi
    log_fail "FaaS smoke failed"
    print_diagnostics "faas_smoke"
    exit 1
}

print_summary() {
    echo ""
    echo "========================================"
    if [ "${SMOKE_FAILED}" -eq 0 ]; then
        echo -e "        ${GREEN}SMOKE RESULT: PASS${NC}"
    else
        echo -e "        ${RED}SMOKE RESULT: FAIL${NC}"
    fi
    echo "========================================"
    echo ""
}

main() {
    echo "=== YuanRong Minimal Python Smoke ==="
    echo "FRONTEND_PORT=${FRONTEND_PORT}"
    echo ""

    check_dev_container
    resolve_python
    resolve_runtime_host
    echo "RUNTIME_HOST=${RUNTIME_HOST}"
    resolve_wheel
    stop_runtime_if_present
    install_wheel
    check_ports
    start_runtime
    wait_ready
    run_sdk_smoke
    run_faas_smoke
    print_summary

    if [ "${SMOKE_FAILED}" -ne 0 ]; then
        exit 1
    fi
}

main "$@"
