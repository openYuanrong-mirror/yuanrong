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

usage() {
    cat <<EOF
Usage: bash $0 -a <ip:port> [-p python_path] [-- pytest args...]

Options:
    -a  Cluster address (required), e.g. 100.111.54.22:38888
    -p  Python binary path (default: auto-detect py39)
    -h  Show this help

Examples:
    bash $0 -a 100.111.54.22:38888
    bash $0 -a 100.111.54.22:38888 -p /usr/bin/python3.9
    bash $0 -a 100.111.54.22:38888 -- -k test_put_get
EOF
}

# Parse args before --
while getopts "a:p:h" opt; do
    case "${opt}" in
        a) SERVER_ADDRESS="${OPTARG}" ;;
        p) PYTHON_BIN="${OPTARG}" ;;
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

# Auto-detect Python 3.9
if [ -z "${PYTHON_BIN}" ]; then
    # Prefer miniforge/conda py39
    for candidate in \
        /Users/wangyuchao/miniforge3/envs/py39/bin/python \
        /opt/homebrew/bin/python3.9 \
        /usr/local/bin/python3.9 \
        python3.9; do
        if command -v "${candidate}" &>/dev/null; then
            PYTHON_BIN="${candidate}"
            break
        fi
    done
fi

if [ -z "${PYTHON_BIN}" ]; then
    echo "ERROR: Python 3.9 not found. Install it or specify -p <path>"
    exit 1
fi

echo "=== Off-Cluster (云外) openyuanrong Smoke Test ==="
echo "Python:    ${PYTHON_BIN}"
echo "Cluster:   ${SERVER_ADDRESS}"
echo "Test dir:  ${TEST_DIR}"
echo ""

# Verify openyuanrong is installed
PKG=$("${PYTHON_BIN}" -c "import yr; print('ok')" 2>&1) || {
    echo "ERROR: openyuanrong package not importable with ${PYTHON_BIN}"
    echo "  ${PKG}"
    exit 1
}

# Verify cluster is reachable
PROTO="https"
STATUS=$(curl -sk -o /dev/null -w "%{http_code}" "${PROTO}://${SERVER_ADDRESS}/" 2>&1) || {
    echo "ERROR: Cannot reach cluster at ${PROTO}://${SERVER_ADDRESS}"
    exit 1
}
echo "Cluster HTTP status: ${STATUS}"
echo ""

# Run tests
cd "${TEST_DIR}"

export YR_SERVER_ADDRESS="${SERVER_ADDRESS}"

echo "--- Running tests ---"
"${PYTHON_BIN}" -m pytest -s -vv \
    --override-ini="confcutdir=${TEST_DIR}" \
    -p no:conftest \
    test_off_cluster.py \
    "${PYTEST_ARGS[@]+"${PYTEST_ARGS[@]}"}"

EXIT_CODE=$?

echo ""
if [ ${EXIT_CODE} -eq 0 ]; then
    echo "=== ALL TESTS PASSED ==="
else
    echo "=== TESTS FAILED (exit code: ${EXIT_CODE}) ==="
fi

exit ${EXIT_CODE}
