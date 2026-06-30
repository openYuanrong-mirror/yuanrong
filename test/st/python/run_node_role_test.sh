#!/usr/bin/env bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Run node_role ST tests against a manually-deployed or k8s cluster.
#
# Usage:
#   bash run_node_role_test.sh [--smoke] [--large-scale] [--restart] [options]
#
# Options:
#   --smoke          run smoke-tagged node_role tests only (fast)
#   --large-scale    run large-scale stress tests (slow)
#   --restart        run worker-role restart stability tests (slow, modifies live process)
#   --all            run all node_role tests
#   -k EXPR          pass -k to pytest
#   -v               verbose pytest output
#
# Environment overrides (all have defaults matching the hand-started 2-node cluster):
#   YR_WORKER_DS_ADDRESS       worker-role ds_worker address  (default: 172.21.0.5:24869)
#   YR_WORKER_PROXY_ADDRESS    worker-role proxy gRPC address (default: 172.21.0.5:37711)
#   YR_MASTER_DS_ADDRESS       master-role ds_worker address  (default: 172.21.0.5:24883)
#   YR_MASTER_PROXY_ADDRESS    master-role proxy gRPC address (default: 172.21.0.5:21766)
#   YR_WORKER_DEPLOY_PATH      deploy_path for worker-role node (default: /tmp/bbb)
#   GLOG_log_dir               log directory                  (default: /tmp/yr_node_role_test)

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${SCRIPT_DIR}"

# ---- defaults ----
IP=${YR_IP:-172.21.0.5}
export YR_WORKER_DS_ADDRESS="${YR_WORKER_DS_ADDRESS:-${IP}:24869}"
export YR_WORKER_PROXY_ADDRESS="${YR_WORKER_PROXY_ADDRESS:-${IP}:37711}"
export YR_MASTER_DS_ADDRESS="${YR_MASTER_DS_ADDRESS:-${IP}:24883}"
export YR_MASTER_PROXY_ADDRESS="${YR_MASTER_PROXY_ADDRESS:-${IP}:21766}"
export YR_WORKER_DEPLOY_PATH="${YR_WORKER_DEPLOY_PATH:-/tmp/bbb}"
export GLOG_log_dir="${GLOG_log_dir:-/tmp/yr_node_role_test}"
mkdir -p "${GLOG_log_dir}"

PYTEST_EXTRA=()
MARKER="node_role"
VERBOSE="-v"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --smoke)      MARKER="node_role and smoke"; shift ;;
        --large-scale) MARKER="node_role and slow"; shift ;;
        --restart)    MARKER="node_role and slow and restart"; shift ;;
        --all)        MARKER="node_role"; shift ;;
        -k)           PYTEST_EXTRA+=("-k" "$2"); shift 2 ;;
        -v)           VERBOSE="-vv"; shift ;;
        *)            echo "unknown option: $1"; exit 1 ;;
    esac
done

echo "====== node_role ST test ======"
echo "  worker ds  : ${YR_WORKER_DS_ADDRESS}"
echo "  worker proxy: ${YR_WORKER_PROXY_ADDRESS}"
echo "  master ds  : ${YR_MASTER_DS_ADDRESS}"
echo "  master proxy: ${YR_MASTER_PROXY_ADDRESS}"
echo "  log dir    : ${GLOG_log_dir}"
echo "  marker     : ${MARKER}"
echo "=============================="

python3.9 -m pytest ${VERBOSE} -s -m "${MARKER}" \
    "${PYTEST_EXTRA[@]}" \
    test_node_role.py \
    2>&1 | tee "${GLOG_log_dir}/node_role_output.txt"

rc=${PIPESTATUS[0]}
if [[ $rc -eq 0 ]]; then
    echo "====== node_role tests PASSED ======"
else
    echo "====== node_role tests FAILED (rc=$rc) ======"
    grep "FAILED\|ERROR" "${GLOG_log_dir}/node_role_output.txt" || true
    exit $rc
fi
