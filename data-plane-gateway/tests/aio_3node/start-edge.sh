#!/usr/bin/env bash
set -euo pipefail

: "${YR_GATEWAY_E2E_ETCD:?YR_GATEWAY_E2E_ETCD is required}"

tls_dir=/tmp/yr-edge-frontend-tls
mkdir -p "${tls_dir}"
if [ ! -s "${tls_dir}/tls.crt" ] || [ ! -s "${tls_dir}/tls.key" ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=edge-frontend \
    -addext 'subjectAltName=DNS:edge-frontend,IP:10.250.0.20,IP:127.0.0.1' \
    -keyout "${tls_dir}/tls.key" -out "${tls_dir}/tls.crt" >/dev/null 2>&1
fi

exec /usr/local/bin/yr start \
  --edge \
  --block true \
  -s "values.edge_frontend.etcd_endpoints=[\"${YR_GATEWAY_E2E_ETCD}\"]" \
  -s 'values.edge_frontend.tls_bind="0.0.0.0:8443"' \
  -s 'values.edge_frontend.plain_bind="0.0.0.0:8080"' \
  -s 'values.edge_frontend.health_bind="0.0.0.0:18080"' \
  -s "values.edge_frontend.tls_cert=\"${tls_dir}/tls.crt\"" \
  -s "values.edge_frontend.tls_key=\"${tls_dir}/tls.key\"" \
  -s 'values.edge_frontend.validate_iam=false' \
  -s 'values.edge_frontend.node_security_mode="network"' \
  -s 'values.edge_frontend.allow_any_client=true' \
  -s 'values.edge_frontend.log_level="info"'
