#!/usr/bin/env bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# ... (same Apache-2.0 header as above)

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")"; pwd)
TEST_DIR="${SCRIPT_DIR}/python"

# Defaults
SERVER_ADDRESS=""
PYTHON_BIN=""
EXTRA_ARGS=""
JWT_TOKEN="${YR_JWT_TOKEN:-}"
ENABLE_TLS="${YR_ENABLE_TLS:-true}"

usage() {
    cat <<EOF
Usage: bash $0 -a <ip:port> [-p python_path] [-t jwt_token] [-- pytest args...]

Options:
    -a  Cluster address (required), e.g. <server-ip>:<port>
    -p  Python binary path (default: prefer active conda/current Python, then common local envs)
    -t  JWT token for X-Auth authentication (default: read from YR_JWT_TOKEN)
    YR_ENABLE_TLS=false may be used for non-TLS off-cluster endpoints.
    -h  Show this help

Examples:
    conda activate py310 && bash $0 -a <server-ip>:<port>
    bash $0 -a <server-ip>:<port>
    bash $0 -a <server-ip>:<port> -p /usr/bin/python3.9
    bash $0 -a <server-ip>:<port> -t <jwt_token>
    export YR_JWT_TOKEN=<jwt_token> && bash $0 -a <server-ip>:<port>
    bash $0 -a <server-ip>:<port> -- -k test_put_get
EOF
}

# Parse args before --
while getopts "a:p:t:h" opt; do
    case "${opt}" in
        a) SERVER_ADDRESS="${OPTARG}" ;;
        p) PYTHON_BIN="${OPTARG}" ;;
        t) JWT_TOKEN="${OPTARG}" ;;
        h) usage; exit 0 ;;
        *) usage; exit 1 ;;
    esac
done
shift $((OPTIND - 1))

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

# Auto-detect a usable Python with openyuanrong installed
if [ -z "${PYTHON_BIN}" ]; then
    PYTHON_BIN=$(find_usable_python || true)
fi

if [ -z "${PYTHON_BIN}" ]; then
    echo "ERROR: No usable Python with openyuanrong installed was found. Activate your conda env or specify -p <path>"
    exit 1
fi

echo "=== Off-Cluster (云外) openyuanrong Smoke Test ==="
echo "Python:    ${PYTHON_BIN}"
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
