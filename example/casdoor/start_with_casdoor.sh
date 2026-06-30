#!/bin/bash

# Casdoor One-Click Startup Script for Yuanrong
# This script starts Casdoor and prepares environment for iam-server.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
CASDOOR_DIR="${SCRIPT_DIR}"

refresh_casdoor_jwt_cert() {
  local endpoint="${CASDOOR_ENDPOINT:-http://casdoor:8000}"
  local cert_file="${CASDOOR_DIR}/token_jwt_key.pem"
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

# echo "==== Step 1: Starting Casdoor Containers ===="
# cd "${CASDOOR_DIR}"
# docker-compose up -d

# echo "Waiting for Casdoor to be ready..."
# until curl -s http://localhost:8000 > /dev/null; do
#   sleep 2
#   echo -n "."
# done
# echo -e "\nCasdoor is UP at http://localhost:8000"

echo "==== Step 2: Configuring Environment ===="
# These are default credentials for a fresh Casdoor installation
export AUTH_PROVIDER=casdoor
export CASDOOR_ENABLED=true
# CASDOOR_ENDPOINT is for server-to-server internal calls
export CASDOOR_ENDPOINT=http://casdoor:8000
# CASDOOR_PUBLIC_ENDPOINT is what the user's browser will see via Traefik
export CASDOOR_PUBLIC_ENDPOINT=http://wyc.pc:18888
export CASDOOR_CLIENT_ID=0ba5201231730ca88978
export CASDOOR_CLIENT_SECRET=123456
export CASDOOR_ORGANIZATION=openyuanrong.org
export CASDOOR_APPLICATION=yuanrong

refresh_casdoor_jwt_cert

# Automatically read the public key from the pem file if it exists
PUB_KEY_FILE="${CASDOOR_DIR}/token_jwt_key.pem"
if [ -f "${PUB_KEY_FILE}" ]; then
  echo "Found public key at ${PUB_KEY_FILE}, importing..."
  export CASDOOR_JWT_PUBLIC_KEY=$(cat "${PUB_KEY_FILE}")
else
  echo "Warning: ${PUB_KEY_FILE} not found. You may need to set CASDOOR_JWT_PUBLIC_KEY manually."
  export CASDOOR_JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----
(PLEASE_COPY_FROM_CASDOOR_UI_OR_ADD_PEM_FILE)
-----END PUBLIC KEY-----"
fi

echo "==== Step 3: Instructions ===="
echo "Casdoor is running. Default Admin: admin / 123"
echo "To start iam-server with these settings, run:"
echo "  source ./start_with_casdoor.sh (to keep env vars)"
echo "  ./functionsystem/scripts/deploy/function_system/install.sh iam_server"
echo "=============================="
