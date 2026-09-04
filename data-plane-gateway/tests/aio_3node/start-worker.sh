#!/usr/bin/env bash
set -euo pipefail

AIO_NODE_IP="$(hostname -i | awk '{print $1}')"
export MY_ENV=myenv LD_LIBRARY_PATH=:/testEnv PYTHONPATH=:/testpythonpayh

exec /usr/local/bin/yr start \
  --master_address "http://__MASTER_IP__:__GLOBAL_SCHEDULER_PORT__" \
  --function-proxy-merge-process-enable \
  --block true \
  -s "values.host_ip=\"${AIO_NODE_IP}\"" \
  -s 'values.ds_master.ip="__MASTER_IP__"' \
  -s 'values.ds_master.port=__DS_MASTER_PORT__' \
  -s 'ds_worker.args.master_address="__MASTER_IP__:__DS_MASTER_PORT__"' \
  -s 'values.runtime_launcher.enable=true' \
  -s 'values.node_proxy.enabled=true' \
  -s "values.node_proxy.advertise_address=\"${AIO_NODE_IP}:8443\"" \
  -s 'values.node_proxy.health_bind="0.0.0.0:18443"' \
  -s 'values.node_proxy.allowed_target_cidrs=["172.16.0.0/12"]' \
  -s 'values.node_proxy.allow_any_edge=true' \
  -s 'values.node_proxy.edge_security_mode="network"' \
  -s 'values.node_proxy.activity_interval_sec=2' \
  -s 'values.node_proxy.log_level="info"' \
  -s 'function_proxy.args.system_timeout=12000' \
  -s 'function_proxy.args.enable_inherit_env=true' \
  -s 'function_proxy.args.custom_resources="{\"__NODE_TAG__\":3,\"node\":1}"'
