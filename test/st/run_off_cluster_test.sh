#!/usr/bin/env bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# ... (same Apache-2.0 header as above)

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")"; pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.."; pwd)
TEST_DIR="${SCRIPT_DIR}/python"

# Defaults
SERVER_ADDRESS=""
PYTHON_BIN=""
USE_UV_VENV="${YR_OFF_CLUSTER_USE_UV_VENV:-true}"
VERIFY_VENV="${YR_OFF_CLUSTER_VENV:-/tmp/yr-offcluster-venv}"
WHEEL_DIR="${YR_OFF_CLUSTER_WHEEL_DIR:-${REPO_ROOT}/output}"
JWT_TOKEN="${YR_JWT_TOKEN:-}"
ENABLE_TLS="${YR_ENABLE_TLS:-true}"

usage() {
    cat <<EOF
Usage: bash $0 -a <ip:port> [-p python_path] [-t jwt_token] [--no-uv-venv] [-- pytest args...]

Options:
    -a  Cluster address (required), e.g. <server-ip>:<port>
    -p  Base Python used to create the uv verification venv
        (default: python3.10; with --no-uv-venv, Python used directly)
    -t  JWT token for X-Auth authentication (default: read from YR_JWT_TOKEN)
    --no-uv-venv
        Use the selected Python directly instead of creating a uv venv from output wheels.
    YR_ENABLE_TLS=false may be used for non-TLS off-cluster endpoints.
    YR_OFF_CLUSTER_VENV may override the uv venv path (default: ${VERIFY_VENV}).
    YR_OFF_CLUSTER_WHEEL_DIR may override the wheel directory used by uv
        (default: ${REPO_ROOT}/output).
    -h  Show this help

Examples:
    bash $0 -a <server-ip>:<port>
    bash $0 -a <server-ip>:<port> -p /usr/bin/python3.10
    bash $0 -a <server-ip>:<port> --no-uv-venv -p /path/to/installed/python
    bash $0 -a <server-ip>:<port> -t <jwt_token>
    export YR_JWT_TOKEN=<jwt_token> && bash $0 -a <server-ip>:<port>
    bash $0 -a <server-ip>:<port> -- -k test_put_get
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -a)
            SERVER_ADDRESS="$2"; shift 2 ;;
        -p)
            PYTHON_BIN="$2"; shift 2 ;;
        -t)
            JWT_TOKEN="$2"; shift 2 ;;
        --no-uv-venv)
            USE_UV_VENV=false; shift ;;
        -h|--help)
            usage; exit 0 ;;
        --)
            shift
            break ;;
        -*)
            usage; exit 1 ;;
        *)
            break ;;
    esac
done

# Everything after -- is passed to pytest
PYTEST_ARGS=("$@")

if [ -z "${SERVER_ADDRESS}" ]; then
    echo "ERROR: -a <ip:port> is required"
    usage
    exit 1
fi

find_usable_python() {
    local candidate=""
    local resolved=""
    local candidates=()

    if [ -n "${CONDA_PREFIX:-}" ]; then
        candidates+=("${CONDA_PREFIX}/bin/python")
    fi

    candidates+=(
        python
        python3
        python3.10
        python3.9
    )

    for candidate in "${candidates[@]}"; do
        if ! command -v "${candidate}" &>/dev/null; then
            continue
        fi

        resolved=$(command -v "${candidate}")
        if "${resolved}" -c "import yr" &>/dev/null; then
            printf '%s\n' "${resolved}"
            return 0
        fi
    done

    return 1
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
        echo "ERROR: Missing required artifact matching ${pattern}" >&2
        return 1
    fi
    if [ "${#matches[@]}" -ne 1 ]; then
        echo "ERROR: Expected exactly one artifact matching ${pattern}, found ${#matches[@]}" >&2
        printf '%s\n' "${matches[@]}" >&2
        return 1
    fi

    printf '%s\n' "${matches[0]}"
}

prepare_uv_venv() {
    local base_python="$1"
    local sdk_wheel
    local runtime_wheel

    if ! command -v uv >/dev/null 2>&1; then
        echo "ERROR: uv is required for the default off-cluster verification venv." >&2
        echo "       Install uv or pass --no-uv-venv with a Python that already has openyuanrong installed." >&2
        exit 1
    fi

    sdk_wheel="$(resolve_single_file "${WHEEL_DIR}/openyuanrong_sdk*.whl")"
    runtime_wheel="$(resolve_single_file "${WHEEL_DIR}/openyuanrong-*.whl")"

    rm -rf "${VERIFY_VENV}"
    uv venv --python "${base_python}" "${VERIFY_VENV}"
    uv pip install --python "${VERIFY_VENV}/bin/python" \
        --no-cache \
        "${sdk_wheel}" \
        "${runtime_wheel}" \
        pytest

    PYTHON_BIN="${VERIFY_VENV}/bin/python"
}

if is_enabled "${USE_UV_VENV}"; then
    if [ -z "${PYTHON_BIN}" ]; then
        PYTHON_BIN="python3.10"
    fi
    prepare_uv_venv "${PYTHON_BIN}"
else
    # Auto-detect a usable Python with openyuanrong installed.
    if [ -z "${PYTHON_BIN}" ]; then
        PYTHON_BIN=$(find_usable_python || true)
    fi
fi

if [ -z "${PYTHON_BIN}" ]; then
    echo "ERROR: No usable Python with openyuanrong installed was found. Activate your conda env or specify -p <path>"
    exit 1
fi

echo "=== Off-Cluster (云外) openyuanrong Smoke Test ==="
echo "Python:    ${PYTHON_BIN}"
if is_enabled "${USE_UV_VENV}"; then
    echo "Venv:      ${VERIFY_VENV}"
fi
echo "Cluster:   ${SERVER_ADDRESS}"
echo "Test dir:  ${TEST_DIR}"
if [ -n "${JWT_TOKEN}" ]; then
    echo "Auth:      enabled (X-Auth)"
else
    echo "Auth:      disabled"
fi
echo ""

# Verify openyuanrong is installed
PKG=$("${PYTHON_BIN}" -c "import yr; print('ok')" 2>&1) || {
    echo "ERROR: openyuanrong package not importable with ${PYTHON_BIN}"
    echo "  ${PKG}"
    exit 1
}

# Verify cluster is reachable
case "${ENABLE_TLS}" in
    1|true|TRUE|yes|YES|on|ON) PROTO="https" ;;
    0|false|FALSE|no|NO|off|OFF) PROTO="http" ;;
    *)
        echo "ERROR: YR_ENABLE_TLS must be true or false, got: ${ENABLE_TLS}"
        exit 1
        ;;
esac
if [ -n "${JWT_TOKEN}" ]; then
    CURL_AUTH_ARGS=(-H "X-Auth: ${JWT_TOKEN}")
else
    CURL_AUTH_ARGS=()
fi
STATUS=$(curl -sk "${CURL_AUTH_ARGS[@]}" -o /dev/null -w "%{http_code}" "${PROTO}://${SERVER_ADDRESS}/" 2>&1) || {
    echo "ERROR: Cannot reach cluster at ${PROTO}://${SERVER_ADDRESS}"
    exit 1
}
echo "Cluster HTTP status: ${STATUS}"
echo ""

# Run tests
cd "${TEST_DIR}"

export YR_SERVER_ADDRESS="${SERVER_ADDRESS}"
export YR_JWT_TOKEN="${JWT_TOKEN}"
export YR_ENABLE_TLS="${ENABLE_TLS}"

echo "--- Running tests ---"
PYTEST_CMD=(
    "${PYTHON_BIN}" -m pytest -s -vv
    --override-ini="confcutdir=${TEST_DIR}"
    -p no:conftest
    test_off_cluster.py
    "${PYTEST_ARGS[@]}"
)

set +e
if command -v timeout >/dev/null 2>&1; then
    timeout "${YR_OFF_CLUSTER_TEST_TIMEOUT:-600}" "${PYTEST_CMD[@]}"
else
    "${PYTEST_CMD[@]}"
fi

EXIT_CODE=$?
set -e

echo ""
if [ ${EXIT_CODE} -eq 0 ]; then
    echo "=== ALL TESTS PASSED ==="
else
    echo "=== TESTS FAILED (exit code: ${EXIT_CODE}) ==="
fi

exit ${EXIT_CODE}
