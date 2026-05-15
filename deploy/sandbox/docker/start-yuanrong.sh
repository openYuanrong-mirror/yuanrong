#!/usr/bin/env bash

set -euo pipefail

AIO_NODE_IP="$(hostname -i | awk '{print $1}')"

exec /usr/local/bin/yr start \
  --master \
  --block true \
  --port_policy FIX \
  --enable_faas_frontend=true \
  --faas_frontend_http_port 8889 \
  --enable_traefik_registry true \
  --traefik_http_entrypoint web \
  --traefik_enable_tls false \
  --enable_function_scheduler true \
  --function_scheduler_lease_port 8890 \
  --enable_meta_service true \
  --frontend_ssl_enable false \
  --enable_iam_server "${ENABLE_TOKEN:-false}" \
  --frontend_client_auth_type NoClientCert \
  --enable_function_token_auth "${ENABLE_TOKEN:-false}" \
  -a "${AIO_NODE_IP}" \
  -p /openyuanrong/services.yaml
