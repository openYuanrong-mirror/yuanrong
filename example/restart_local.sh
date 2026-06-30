#!/usr/bin/env bash
# YuanRong Runtime Local Restart Script
# Fast restart without reinstalling Python wheels.

set -e

TYPE="$1"
if [ -z "$TYPE" ]; then
    TYPE="http"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

refresh_casdoor_jwt_cert() {
    local endpoint="${CASDOOR_ENDPOINT:-http://casdoor:8000}"
    local cert_file="${SCRIPT_DIR}/casdoor/token_jwt_key.pem"
    local jwks
    local cert

    if ! command -v python3 >/dev/null 2>&1; then
        echo "python3 not found, skipping Casdoor JWT cert refresh"
        return 0
    fi

    jwks=$(curl -fsS "${endpoint}/.well-known/jwks" 2>/dev/null || true)
    if [ -z "${jwks}" ]; then
        echo "Warning: failed to fetch Casdoor JWKS from ${endpoint}, keeping existing JWT cert"
        return 0
    fi

    cert=$(printf '%s' "${jwks}" | python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
    keys = data.get("keys") or []
    x5c = keys[0].get("x5c") or []
    value = x5c[0]
except Exception:
    sys.exit(1)

print("-----BEGIN CERTIFICATE-----")
for i in range(0, len(value), 64):
    print(value[i:i + 64])
print("-----END CERTIFICATE-----")
' 2>/dev/null || true)

    if [ -z "${cert}" ]; then
        echo "Warning: failed to parse Casdoor JWKS certificate, keeping existing JWT cert"
        return 0
    fi

    printf '%s\n' "${cert}" > "${cert_file}"
    echo "Refreshed Casdoor JWT public key at ${cert_file}"
}

echo "=== YuanRong Runtime Local Restart ==="
echo "Project root: ${PROJECT_ROOT}"
echo ""

echo "Step 1: Stopping existing runtime..."
yr stop 2>/dev/null || echo "No running instance found"

echo ""
echo "Step 2: Starting runtime without reinstalling packages..."
export LITEBUS_DATA_KEY=6D792D7365637265742D6B65792D666F722D6A77742D64656D6F
export CONTAINER_EP=unix:///tmp/yr_sessions/runtime-launcher.sock

KEYCLOAK_ENV_FILE="${SCRIPT_DIR}/keycloak/.keycloak.env"
if [ -f "${KEYCLOAK_ENV_FILE}" ]; then
    # shellcheck source=/dev/null
    source "${KEYCLOAK_ENV_FILE}"
    echo "Loaded Keycloak env from ${KEYCLOAK_ENV_FILE}"
fi

CASDOOR_ENV_FILE="${SCRIPT_DIR}/casdoor/.casdoor.env"
if [ -f "${CASDOOR_ENV_FILE}" ]; then
    # shellcheck source=/dev/null
    source "${CASDOOR_ENV_FILE}"
    echo "Loaded Casdoor env from ${CASDOOR_ENV_FILE}"
fi

export AUTH_PROVIDER="${AUTH_PROVIDER:-casdoor}"
if [ "${AUTH_PROVIDER}" = "casdoor" ]; then
    export KEYCLOAK_ENABLED="${KEYCLOAK_ENABLED:-false}"
    export CASDOOR_ENABLED="${CASDOOR_ENABLED:-true}"
else
    export KEYCLOAK_ENABLED="${KEYCLOAK_ENABLED:-true}"
    export CASDOOR_ENABLED="${CASDOOR_ENABLED:-false}"
fi

export KEYCLOAK_URL="${KEYCLOAK_URL:-http://wyc.pc:18888}"
export KEYCLOAK_INTERNAL_URL="${KEYCLOAK_INTERNAL_URL:-http://yr-keycloak:8080}"
export KEYCLOAK_REALM="${KEYCLOAK_REALM:-yuanrong}"
export KEYCLOAK_CLIENT_ID="${KEYCLOAK_CLIENT_ID:-frontend}"
export KEYCLOAK_CLIENT_SECRET="${KEYCLOAK_CLIENT_SECRET:-}"

export CASDOOR_ENDPOINT="${CASDOOR_ENDPOINT:-http://casdoor:8000}"
export CASDOOR_PUBLIC_ENDPOINT="${CASDOOR_PUBLIC_ENDPOINT:-http://wyc.pc:18888}"
export CASDOOR_CLIENT_ID="${CASDOOR_CLIENT_ID:-}"
export CASDOOR_CLIENT_SECRET="${CASDOOR_CLIENT_SECRET:-}"
export CASDOOR_ORGANIZATION="${CASDOOR_ORGANIZATION:-openyuanrong.org}"
export CASDOOR_APPLICATION="${CASDOOR_APPLICATION:-yuanrong}"
export CASDOOR_ADMIN_USER="${CASDOOR_ADMIN_USER:-admin}"
export CASDOOR_ADMIN_PASSWORD="${CASDOOR_ADMIN_PASSWORD:-123}"

refresh_casdoor_jwt_cert

CASDOOR_JWT_PUBLIC_KEY_FILE="${SCRIPT_DIR}/casdoor/token_jwt_key.pem"
if [ -z "${CASDOOR_JWT_PUBLIC_KEY:-}" ] && [ -f "${CASDOOR_JWT_PUBLIC_KEY_FILE}" ]; then
    export CASDOOR_JWT_PUBLIC_KEY="$(cat "${CASDOOR_JWT_PUBLIC_KEY_FILE}")"
    echo "Loaded Casdoor JWT public key from ${CASDOOR_JWT_PUBLIC_KEY_FILE}"
fi

echo "Auth provider config:"
echo "  AUTH_PROVIDER=${AUTH_PROVIDER}"
echo "Keycloak config:"
echo "  KEYCLOAK_ENABLED=${KEYCLOAK_ENABLED}"
echo "  KEYCLOAK_URL=${KEYCLOAK_URL}"
echo "  KEYCLOAK_REALM=${KEYCLOAK_REALM}"
echo "  KEYCLOAK_CLIENT_ID=${KEYCLOAK_CLIENT_ID}"
if [ -n "${KEYCLOAK_CLIENT_SECRET}" ]; then
    echo "  KEYCLOAK_CLIENT_SECRET=***"
else
    echo "  KEYCLOAK_CLIENT_SECRET=<empty>"
fi

echo "Casdoor config:"
echo "  CASDOOR_ENABLED=${CASDOOR_ENABLED}"
echo "  CASDOOR_ENDPOINT=${CASDOOR_ENDPOINT}"
echo "  CASDOOR_PUBLIC_ENDPOINT=${CASDOOR_PUBLIC_ENDPOINT}"
echo "  CASDOOR_ORGANIZATION=${CASDOOR_ORGANIZATION}"
echo "  CASDOOR_APPLICATION=${CASDOOR_APPLICATION}"
echo "  CASDOOR_ADMIN_USER=${CASDOOR_ADMIN_USER}"
if [ -n "${CASDOOR_CLIENT_ID}" ]; then
    echo "  CASDOOR_CLIENT_ID=${CASDOOR_CLIENT_ID}"
else
    echo "  CASDOOR_CLIENT_ID=<empty>"
fi
if [ -n "${CASDOOR_CLIENT_SECRET}" ]; then
    echo "  CASDOOR_CLIENT_SECRET=***"
else
    echo "  CASDOOR_CLIENT_SECRET=<empty>"
fi
if [ -n "${CASDOOR_JWT_PUBLIC_KEY:-}" ]; then
    echo "  CASDOOR_JWT_PUBLIC_KEY=loaded"
else
    echo "  CASDOOR_JWT_PUBLIC_KEY=<empty>"
fi
if [ -n "${CASDOOR_ADMIN_PASSWORD:-}" ]; then
    echo "  CASDOOR_ADMIN_PASSWORD=***"
else
    echo "  CASDOOR_ADMIN_PASSWORD=<empty>"
fi

SERVICES_YAML="${SCRIPT_DIR}/webterminal/services.yaml"

echo "Using services.yaml: ${SERVICES_YAML}"

if [ "${TYPE}" = "http" ]; then
    echo "Starting in HTTP mode..."
    yr start --master \
        --enable_faas_frontend=true \
        -l DEBUG \
        --port_policy FIX \
        --enable_function_scheduler true \
        --enable_meta_service true \
        --enable_iam_server true \
        -p "${SERVICES_YAML}"
elif [ "${TYPE}" = "token" ]; then
    echo "Starting in token mode..."
    yr start --master --enable_faas_frontend=true -l DEBUG \
        --port_policy FIX --enable_function_scheduler true \
        --enable_meta_service true \
        --ssl_base_path "${SCRIPT_DIR}/webterminal/cert" \
        --frontend_ssl_enable true \
        --enable_iam_server true \
        --frontend_client_auth_type NoClientCert \
        --enable_function_token_auth true \
        --fs_health_check_retry_times 6000 \
        -p "${SERVICES_YAML}"
elif [ "${TYPE}" = "mtls" ]; then
    echo "Starting in mtls mode..."
    yr start --master --enable_faas_frontend=true -l DEBUG \
        --port_policy FIX --enable_function_scheduler true \
        --enable_meta_service true \
        --ssl_base_path "${SCRIPT_DIR}/webterminal/cert/" \
        --frontend_ssl_enable true \
        --meta_service_ssl_enable true \
        -p "${SERVICES_YAML}"
else
    echo "Unknown type: ${TYPE}. Valid options are: http, token, mtls."
    exit 1
fi

echo ""
echo "=== Runtime restarted successfully ==="
