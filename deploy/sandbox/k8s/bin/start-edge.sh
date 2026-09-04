#!/usr/bin/env bash
set -euo pipefail

umask 0027

edge_ip="${RUNTIME_POD_IP:-$(hostname -i | awk '{print $1}')}"
etcd_addr_list="${YR_ETCD_ADDR_LIST:?Set YR_ETCD_ADDR_LIST for external etcd}"
tls_bind="${YR_DATA_PLANE_EDGE_FRONTEND_TLS_BIND:-0.0.0.0:8443}"
plain_bind="${YR_DATA_PLANE_EDGE_FRONTEND_PLAIN_BIND:-0.0.0.0:8080}"
health_bind="${YR_DATA_PLANE_EDGE_FRONTEND_HEALTH_BIND:-0.0.0.0:18080}"

resolve_host() {
  python3 - "$1" <<'PY'
import socket
import sys

print(socket.gethostbyname(sys.argv[1]))
PY
}

toml_etcd_addresses() {
  local result="" sep="" entry host port resolved_host
  IFS=',' read -ra entries <<< "$1"
  for entry in "${entries[@]}"; do
    host="${entry%:*}"
    port="${entry##*:}"
    resolved_host="$(resolve_host "${host}")"
    result="${result}${sep}{ip=\"${resolved_host}\",peer_port=${port},port=${port}}"
    sep=","
  done
  printf '[%s]' "${result}"
}

toml_string_list() {
  python3 - "$1" <<'PY'
import json
import sys

print(json.dumps([item.strip() for item in sys.argv[1].split(",") if item.strip()]))
PY
}

etcd_addresses="$(toml_etcd_addresses "${etcd_addr_list}")"
allowed_client_cidrs="$(toml_string_list "${YR_DATA_PLANE_EDGE_FRONTEND_ALLOWED_CLIENT_CIDRS:-}")"
default_control_plane_routes="exact:/,exact:/healthz,prefix:/terminal,prefix:/api/instances,prefix:/api/jobs,prefix:/api/sandbox,prefix:/functions,prefix:/api-docs,prefix:/admin/v1/functions,prefix:/serverless/v1/functions,prefix:/serverless/v1/stream,prefix:/serverless/v1/componentshealth,prefix:/serverless/v1/posix,prefix:/frontend/v1/instance,prefix:/datasystem/v1,prefix:/serverless/v2,prefix:/app/v1,prefix:/client/v1/lease,prefix:/invocations,prefix:/global-scheduler"
control_plane_routes="$(toml_string_list "${YR_DATA_PLANE_EDGE_FRONTEND_CONTROL_PLANE_ROUTES:-${default_control_plane_routes}}")"

exec /usr/local/bin/yr start \
  --edge \
  --block true \
  -s "values.host_ip=\"${edge_ip}\"" \
  -s 'values.etcd.enable_multi_master=true' \
  -s "values.etcd.address=${etcd_addresses}" \
  -s "values.edge_frontend.tls_bind=\"${tls_bind}\"" \
  -s "values.edge_frontend.plain_bind=\"${plain_bind}\"" \
  -s "values.edge_frontend.health_bind=\"${health_bind}\"" \
  -s "values.edge_frontend.frontend_address=\"${YR_DATA_PLANE_EDGE_FRONTEND_CONTROL_PLANE_ADDRESS:-127.0.0.1:8888}\"" \
  -s "values.edge_frontend.control_plane_routes=${control_plane_routes}" \
  -s "values.edge_frontend.tls_cert=\"${YR_DATA_PLANE_EDGE_FRONTEND_TLS_CERT:-}\"" \
  -s "values.edge_frontend.tls_key=\"${YR_DATA_PLANE_EDGE_FRONTEND_TLS_KEY:-}\"" \
  -s "values.edge_frontend.validate_iam=${YR_DATA_PLANE_EDGE_FRONTEND_VALIDATE_IAM:-true}" \
  -s "values.edge_frontend.iam_address=\"${YR_DATA_PLANE_EDGE_FRONTEND_IAM_ADDRESS:-}\"" \
  -s "values.edge_frontend.auth_cache_ttl_sec=${YR_DATA_PLANE_EDGE_FRONTEND_AUTH_CACHE_TTL_SEC:-30}" \
  -s "values.edge_frontend.default_direct_port=${YR_DATA_PLANE_EDGE_FRONTEND_DIRECT_PORT:-50090}" \
  -s "values.edge_frontend.default_tunnel_port=${YR_DATA_PLANE_EDGE_FRONTEND_TUNNEL_PORT:-8765}" \
  -s "values.edge_frontend.backend_http_max_connections_per_endpoint=${YR_DATA_PLANE_EDGE_FRONTEND_BACKEND_HTTP_MAX_CONNECTIONS_PER_ENDPOINT:-64}" \
  -s "values.edge_frontend.backend_http_max_idle_connections=${YR_DATA_PLANE_EDGE_FRONTEND_BACKEND_HTTP_MAX_IDLE_CONNECTIONS:-1024}" \
  -s "values.edge_frontend.backend_http_max_idle_connections_per_endpoint=${YR_DATA_PLANE_EDGE_FRONTEND_BACKEND_HTTP_MAX_IDLE_CONNECTIONS_PER_ENDPOINT:-64}" \
  -s "values.edge_frontend.backend_http_idle_timeout_sec=${YR_DATA_PLANE_EDGE_FRONTEND_BACKEND_HTTP_IDLE_TIMEOUT_SEC:-5}" \
  -s "values.edge_frontend.backend_http_acquire_timeout_ms=${YR_DATA_PLANE_EDGE_FRONTEND_BACKEND_HTTP_ACQUIRE_TIMEOUT_MS:-3000}" \
  -s "values.edge_frontend.node_security_mode=\"${YR_DATA_PLANE_EDGE_FRONTEND_NODE_SECURITY_MODE:-network}\"" \
  -s "values.edge_frontend.node_tls_ca=\"${YR_DATA_PLANE_EDGE_FRONTEND_NODE_TLS_CA:-}\"" \
  -s "values.edge_frontend.node_tls_server_name=\"${YR_DATA_PLANE_EDGE_FRONTEND_NODE_TLS_SERVER_NAME:-}\"" \
  -s "values.edge_frontend.node_tls_client_cert=\"${YR_DATA_PLANE_EDGE_FRONTEND_NODE_TLS_CLIENT_CERT:-}\"" \
  -s "values.edge_frontend.node_tls_client_key=\"${YR_DATA_PLANE_EDGE_FRONTEND_NODE_TLS_CLIENT_KEY:-}\"" \
  -s "values.edge_frontend.allowed_client_cidrs=${allowed_client_cidrs}" \
  -s "values.edge_frontend.allow_any_client=${YR_DATA_PLANE_EDGE_FRONTEND_ALLOW_ANY_CLIENT:-false}" \
  -s "values.edge_frontend.log_level=\"${YR_DATA_PLANE_EDGE_FRONTEND_LOG_LEVEL:-info}\"" \
  -s "values.edge_frontend.command_watch_max_subscriptions=${YR_COMMAND_WATCH_MAX_SUBSCRIPTIONS_PER_CONNECTION:-4096}" \
  -s "values.edge_frontend.command_watch_queue_capacity=${YR_COMMAND_WATCH_QUEUE_CAPACITY:-256}" \
  -s "values.edge_frontend.command_watch_max_frame_bytes=${YR_COMMAND_WATCH_MAX_FRAME_BYTES:-1048576}" \
  -s "values.edge_frontend.command_watch_ping_interval_sec=${YR_COMMAND_WATCH_PING_INTERVAL_SECS:-20}" \
  "$@"
