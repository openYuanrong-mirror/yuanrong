#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

set -euo pipefail

BASE_DIR=$(cd "$(dirname "$0")" && pwd)
config_script="${BASE_DIR}/config.sh"
deploy_script="${BASE_DIR}/deploy.sh"
install_script="${BASE_DIR}/../../functionsystem/scripts/deploy/function_system/install.sh"
test_tmp_dir=$(mktemp -d)
trap 'rm -rf "${test_tmp_dir}"' EXIT

printf '%s\n' test-cert >"${test_tmp_dir}/tls.crt"
printf '%s\n' test-key >"${test_tmp_dir}/tls.key"

common_args=(
  --master
  --ip_address 127.0.0.1
  --only_check_param
  --deploy_path "${test_tmp_dir}/deploy"
)

function expect_accepted() {
  local description=$1
  shift
  local output="${test_tmp_dir}/accepted.out"
  if ! bash "${config_script}" "${common_args[@]}" "$@" >"${output}" 2>&1; then
    cat "${output}" >&2
    echo "${description} must be accepted" >&2
    exit 1
  fi
}

function expect_rejected() {
  local description=$1
  shift
  local output="${test_tmp_dir}/rejected.out"
  if bash "${config_script}" "${common_args[@]}" "$@" >"${output}" 2>&1; then
    echo "${description} must be rejected" >&2
    exit 1
  fi
}

expect_accepted "Node Proxy network mode" \
  --enable_node_proxy true \
  --node_proxy_allowed_target_cidrs 10.88.0.0/16 \
  --node_proxy_allow_any_edge true

expect_accepted "Edge Frontend with configurable routes" \
  --enable_edge_frontend true \
  --edge_frontend_tls_cert "${test_tmp_dir}/tls.crt" \
  --edge_frontend_tls_key "${test_tmp_dir}/tls.key" \
  --edge_frontend_validate_iam false \
  --edge_frontend_allow_any_client true \
  --edge_frontend_control_plane_routes exact:/healthz,prefix:/api/custom \
  --data_plane_log_dir "${test_tmp_dir}/data-plane-logs" \
  --data_plane_log_max_size_mb 8 \
  --data_plane_log_max_files 3 \
  --data_plane_log_stdout false \
  --edge_frontend_access_log_enabled true

expect_accepted "co-located Edge and Node on separate ports" \
  --enable_node_proxy true \
  --node_proxy_bind 0.0.0.0:9443 \
  --node_proxy_allowed_target_cidrs 10.88.0.0/16 \
  --node_proxy_allow_any_edge true \
  --enable_edge_frontend true \
  --edge_frontend_tls_cert "${test_tmp_dir}/tls.crt" \
  --edge_frontend_tls_key "${test_tmp_dir}/tls.key" \
  --edge_frontend_validate_iam false \
  --edge_frontend_allow_any_client true

expect_rejected "Node Proxy without target CIDR" \
  --enable_node_proxy true \
  --node_proxy_allow_any_edge true

expect_rejected "Edge Frontend without TLS identity" \
  --enable_edge_frontend true \
  --edge_frontend_validate_iam false \
  --edge_frontend_allow_any_client true

expect_rejected "co-located Edge and Node port collision" \
  --enable_node_proxy true \
  --node_proxy_allowed_target_cidrs 10.88.0.0/16 \
  --node_proxy_allow_any_edge true \
  --enable_edge_frontend true \
  --edge_frontend_tls_cert "${test_tmp_dir}/tls.crt" \
  --edge_frontend_tls_key "${test_tmp_dir}/tls.key" \
  --edge_frontend_validate_iam false \
  --edge_frontend_allow_any_client true

expect_rejected "zero-sized rolling log" \
  --data_plane_log_max_size_mb 0

expect_rejected "invalid access log switch" \
  --edge_frontend_access_log_enabled sometimes

expect_accepted "command recovery budgets" \
  --command_watch_max_subscriptions 128 \
  --command_watch_queue_capacity 64 \
  --command_watch_max_frame_bytes 65536 \
  --command_watch_ping_interval_secs 15 \
  --command_activity_timeout_secs 45 \
  --rrt_command_result_ttl_secs 600 \
  --rrt_command_stdout_limit_bytes 1024 \
  --rrt_command_stderr_limit_bytes 2048 \
  --rrt_command_registry_max_records 100 \
  --rrt_command_registry_max_bytes 8192 \
  --rrt_command_registry_memory_high_watermark_bytes 4096 \
  --rrt_command_activity_heartbeat_secs 10

expect_accepted "disabled Frontend create advertisement" \
  --advertise_frontend_proxy_create false

expect_rejected "invalid Frontend create advertisement" \
  --advertise_frontend_proxy_create sometimes

expect_rejected "zero command watch queue" --command_watch_queue_capacity 0
expect_rejected "registry watermark over hard limit" \
  --rrt_command_registry_max_bytes 1024 \
  --rrt_command_registry_memory_high_watermark_bytes 2048
expect_rejected "command activity lease too short" \
  --command_activity_timeout_secs 20 \
  --rrt_command_activity_heartbeat_secs 10

for token in \
  'function install_node_proxy()' \
  'function install_edge_frontend()' \
  'YR_DATA_PLANE_EDGE_FRONTEND_CONTROL_PLANE_ROUTES="${EDGE_FRONTEND_CONTROL_PLANE_ROUTES}"' \
  'YR_DATA_PLANE_NODE_PROXY_ACTIVITY_UDS_DIR="${NODE_PROXY_ACTIVITY_UDS_DIR}"' \
  'YR_DATA_PLANE_LOG_MAX_SIZE_MB="${DATA_PLANE_LOG_MAX_SIZE_MB}"' \
  'YR_DATA_PLANE_EDGE_FRONTEND_ACCESS_LOG_ENABLED="${EDGE_FRONTEND_ACCESS_LOG_ENABLED}"'; do
  if ! grep -Fq "${token}" "${install_script}"; then
    echo "install.sh is missing ${token}" >&2
    exit 1
  fi
done

if ! grep -Fq -- '--advertise_frontend_proxy_create="${ADVERTISE_FRONTEND_PROXY_CREATE:-true}"' "${install_script}"; then
  echo "install.sh is missing advertise_frontend_proxy_create" >&2
  exit 1
fi

for token in \
  'YR_COMMAND_WATCH_MAX_SUBSCRIPTIONS_PER_CONNECTION="${COMMAND_WATCH_MAX_SUBSCRIPTIONS}"' \
  'YR_COMMAND_WATCH_QUEUE_CAPACITY="${COMMAND_WATCH_QUEUE_CAPACITY}"'; do
  if ! grep -Fq "${token}" "${install_script}"; then
    echo "install.sh is missing command recovery setting ${token}" >&2
    exit 1
  fi
done

edge_install=$(sed -n '/^function install_edge_frontend()/,/^}/p' "${install_script}")
frontend_install=$(sed -n '/^function install_faas_frontend()/,/^}/p' "${install_script}")
for token in \
  'YR_RRT_COMMAND_RESULT_TTL_SECS="${RRT_COMMAND_RESULT_TTL_SECS}"' \
  'YR_RRT_COMMAND_REGISTRY_MAX_BYTES="${RRT_COMMAND_REGISTRY_MAX_BYTES}"'; do
  if ! grep -Fq "${token}" <<<"${frontend_install}"; then
    echo "Frontend install is missing RRT setting ${token}" >&2
    exit 1
  fi
  if grep -Fq "${token}" <<<"${edge_install}"; then
    echo "RRT setting must not be attached to Edge Frontend: ${token}" >&2
    exit 1
  fi
done
for token in \
  'YR_COMMAND_WATCH_MAX_SUBSCRIPTIONS_PER_CONNECTION="${COMMAND_WATCH_MAX_SUBSCRIPTIONS}"' \
  'YR_COMMAND_WATCH_MAX_FRAME_BYTES="${COMMAND_WATCH_MAX_FRAME_BYTES}"'; do
  if ! grep -Fq "${token}" <<<"${frontend_install}"; then
    echo "Frontend install is missing RRT watch setting ${token}" >&2
    exit 1
  fi
done

for removed_token in \
  'data_plane_log_compression' \
  'DATA_PLANE_LOG_COMPRESSION' \
  'YR_DATA_PLANE_LOG_COMPRESSION'; do
  if grep -Fq "${removed_token}" "${config_script}" "${install_script}"; then
    echo "deployment must not expose Rust log compression setting: ${removed_token}" >&2
    exit 1
  fi
done

for token in \
  'start_node_proxy' \
  'start_edge_frontend' \
  'YR_DATA_PLANE_NODE_PROXY_ENABLED="${ENABLE_NODE_PROXY}"'; do
  if ! grep -Fq "${token}" "${deploy_script}"; then
    echo "deploy.sh is missing ${token}" >&2
    exit 1
  fi
done

echo "Rust Edge/Node process configuration tests passed"
