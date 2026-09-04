#!/usr/bin/env bash
set -euo pipefail

AIO_NODE_IP="$(hostname -i | awk '{print $1}')"
export MY_ENV=myenv LD_LIBRARY_PATH=:/testEnv PYTHONPATH=:/testpythonpayh
exec /usr/local/bin/yr start \
  --master \
  --function-proxy-merge-process-enable \
  --block true \
  -s "values.host_ip=\"${AIO_NODE_IP}\"" \
  -s 'values.runtime_launcher.enable=true' \
  -s 'values.node_proxy.enabled=true' \
  -s "values.node_proxy.advertise_address=\"${AIO_NODE_IP}:8443\"" \
  -s 'values.node_proxy.health_bind="0.0.0.0:18443"' \
  -s 'values.node_proxy.allowed_target_cidrs=["172.16.0.0/12"]' \
  -s 'values.node_proxy.allow_any_edge=true' \
  -s 'values.node_proxy.edge_security_mode="network"' \
  -s 'values.node_proxy.activity_interval_sec=2' \
  -s 'values.node_proxy.log_level="info"' \
  -s 'function_master.args.services_path="/openyuanrong/services.yaml"' \
  -s 'function_proxy.args.services_path="/openyuanrong/services.yaml"' \
  -s 'function_master.args.enable_traefik_provider=false' \
  -s 'mode.master.frontend=true' \
  -s 'values.frontend.port=8889' \
  -s 'values.frontend.ssl_enable=false' \
  -s 'values.frontend.client_auth_type="NoClientCert"' \
  -s 'values.frontend.enable_function_token_auth=false' \
  -s "values.frontend.meta_service_address=\"${AIO_NODE_IP}:31182\"" \
  -s 'values.meta_service.port=31182' \
  -s 'mode.master.function_scheduler=false' \
  -s 'mode.master.meta_service=true' \
  -s 'mode.master.iam_server=false' \
  -s 'function_master.args.system_timeout=12000' \
  -s 'function_proxy.args.system_timeout=12000' \
  -s 'function_proxy.args.enable_inherit_env=true' \
  -s 'function_proxy.args.custom_resources="{\"node_tag1\":3,\"node\":1}"'
