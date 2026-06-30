#!/bin/bash

# Casdoor Environment Setup Script for Yuanrong
# This script creates Organization, Application, and configures Quota settings.

set -e

# Casdoor API configuration
CASDOOR_ENDPOINT="http://localhost:8000"
# Public address accessed via Traefik
CASDOOR_PUBLIC_ENDPOINT="http://wyc.pc:18888"
ADMIN_NAME="admin"
ADMIN_PASSWORD="123"
ORGANIZATION="openyuanrong.org"
APPLICATION="yuanrong"
JWT_CERT_FILE="$(dirname "$0")/token_jwt_key.pem"

refresh_casdoor_jwt_cert() {
  local jwks
  local cert

  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found, skipping Casdoor JWT cert refresh"
    return 0
  fi

  jwks=$(curl -fsS "${CASDOOR_ENDPOINT}/.well-known/jwks" 2>/dev/null || true)
  if [ -z "${jwks}" ]; then
    echo "Warning: failed to fetch Casdoor JWKS, keeping existing JWT cert"
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

  printf '%s\n' "${cert}" > "${JWT_CERT_FILE}"
  echo "JWT cert saved to ${JWT_CERT_FILE}"
}

echo "==== 1. Waiting for Casdoor to be ready ===="
until curl -s "${CASDOOR_ENDPOINT}" > /dev/null; do
  sleep 2
  echo -n "."
done
echo -e "\nCasdoor is ready."

echo "==== 2. Logging in as Admin ===="
COOKIE_FILE=$(mktemp)
LOGIN_RESP=$(curl -s -c "${COOKIE_FILE}" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"login\",\"username\":\"${ADMIN_NAME}\",\"password\":\"${ADMIN_PASSWORD}\",\"organization\":\"built-in\",\"application\":\"app-built-in\"}" \
  "${CASDOOR_ENDPOINT}/api/login")

if [[ $LOGIN_RESP != *"\"status\": \"ok\""* && $LOGIN_RESP != *"\"status\":\"ok\""* ]]; then
    echo "Error: Login failed. Check Casdoor status and admin credentials."
    echo "Response: $LOGIN_RESP"
    exit 1
fi

echo "==== 3. Ensuring Organization exists: ${ORGANIZATION} ===="
# Check if organization exists
ORG_EXISTS=$(curl -s -b "${COOKIE_FILE}" "${CASDOOR_ENDPOINT}/api/get-organization?id=admin/${ORGANIZATION}" | jq '.data')

if [ "$ORG_EXISTS" == "null" ]; then
    echo "Creating Organization: ${ORGANIZATION}..."
    NEW_ORG_JSON=$(cat <<EOF
{
  "owner": "admin",
  "name": "$ORGANIZATION",
  "createdTime": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "displayName": "Open YuanRong Organization",
  "websiteUrl": "https://openyuanrong.org",
  "languages": ["en"],
  "passwordType": "plain",
  "passwordOptions": ["AtLeast6"],
  "enableSoftDeletion": false,
  "isDefault": false
}
EOF
)
    curl -s -b "${COOKIE_FILE}" -H "Content-Type: application/json" -X POST -d "${NEW_ORG_JSON}" "${CASDOOR_ENDPOINT}/api/add-organization" > /dev/null
else
    echo "Organization ${ORGANIZATION} already exists."
fi

echo "==== 4. Configuring Organization Custom Fields & Default Quota (100) ===="
# Get latest ORG config
ORG_JSON=$(curl -s -b "${COOKIE_FILE}" "${CASDOOR_ENDPOINT}/api/get-organization?id=admin/${ORGANIZATION}" | jq '.data')

NEW_ORG_CONFIG=$(echo "${ORG_JSON}" | jq '
  .languages = ((.languages // []) | if length == 0 then ["en"] else . end) |
  .customFields = [
    {
      "name": "cpu_quota", 
      "displayName": "CPU Quota", 
      "dataType": "Integer", 
      "modifyRule": "AdminOnly", 
      "defaultValue": "100"
    },
    {
      "name": "mem_quota", 
      "displayName": "Memory Quota (MiB)", 
      "dataType": "Integer", 
      "modifyRule": "AdminOnly", 
      "defaultValue": "100"
    }
  ]
')

curl -s -b "${COOKIE_FILE}" -H "Content-Type: application/json" -X POST -d "${NEW_ORG_CONFIG}" \
  "${CASDOOR_ENDPOINT}/api/update-organization?id=admin/${ORGANIZATION}" > /dev/null

echo "==== 5. Ensuring Application exists: ${APPLICATION} ===="
# Check if application exists
APP_EXISTS=$(curl -s -b "${COOKIE_FILE}" "${CASDOOR_ENDPOINT}/api/get-application?id=admin/${APPLICATION}" | jq '.data')

if [ "$APP_EXISTS" == "null" ]; then
    echo "Creating Application: ${APPLICATION}..."
    # Generate a random Client ID and Secret if not already fixed
    CLIENT_ID=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 20 | head -n 1)
    CLIENT_SECRET=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
    
    NEW_APP_JSON=$(cat <<EOF
{
  "owner": "admin",
  "name": "$APPLICATION",
  "createdTime": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "displayName": "YuanRong Platform",
  "organization": "$ORGANIZATION",
  "clientId": "$CLIENT_ID",
  "clientSecret": "$CLIENT_SECRET",
  "redirectUris": ["$CASDOOR_PUBLIC_ENDPOINT/auth/callback"],
  "enablePassword": true,
  "enableSignUp": true,
  "expireTime": 3600,
  "refreshExpire": 86400
}
EOF
)
    curl -s -b "${COOKIE_FILE}" -H "Content-Type: application/json" -X POST -d "${NEW_APP_JSON}" "${CASDOOR_ENDPOINT}/api/add-application" > /dev/null
else
    echo "Application ${APPLICATION} already exists."
fi

echo "==== 6. Configuring Application UI (Visible Quotas, Admin-Only Edit) ===="
APP_JSON=$(curl -s -b "${COOKIE_FILE}" "${CASDOOR_ENDPOINT}/api/get-application?id=admin/${APPLICATION}" | jq '.data')
EMAIL_PROVIDER_NAME=$(curl -s -b "${COOKIE_FILE}" "${CASDOOR_ENDPOINT}/api/get-providers?owner=admin" | jq -r '.data // [] | map(select(.category == "Email")) | .[0].name // empty')

NEW_APP_CONFIG=$(echo "${APP_JSON}" | jq --arg emailProvider "${EMAIL_PROVIDER_NAME}" '
  .enablePassword = true |
  .enableAutoSignin = false |
  .providers = (
    [
      {
        "name": "provider_captcha_default",
        "canSignUp": false,
        "canSignIn": false,
        "canUnlink": false,
        "rule": "None"
      }
    ] +
    (if $emailProvider != "" then
      [
        {
          "name": $emailProvider,
          "canSignUp": true,
          "canSignIn": true,
          "canUnlink": false,
          "rule": "All"
        }
      ]
    else
      []
    end)
  ) |
  .signupItems = [
    {"name": "Username", "visible": true, "required": true, "rule": "None"},
    {"name": "Password", "visible": true, "required": true, "rule": "None"},
    {"name": "Email", "visible": true, "required": false, "rule": (if $emailProvider != "" then "Normal" else "No verification" end)}
  ] |
  .editItems = [
    {"name": "DisplayName", "label": "Display Name", "visible": true, "viewRule": "None", "modifyRule": "None"},
    {"name": "Email", "label": "Email", "visible": true, "viewRule": "None", "modifyRule": "None"},
    {"name": "cpu_quota", "label": "CPU Quota (Standard)", "visible": true, "viewRule": "None", "modifyRule": "AdminOnly"},
    {"name": "mem_quota", "label": "Memory Quota (Standard)", "visible": true, "viewRule": "None", "modifyRule": "AdminOnly"}
  ]
')

# Update Application
UPDATE_STATUS=$(curl -s -b "${COOKIE_FILE}" -H "Content-Type: application/json" -X POST -d "${NEW_APP_CONFIG}" \
  "${CASDOOR_ENDPOINT}/api/update-application?id=admin/${APPLICATION}" | jq -r '.status')


echo "Application update status: ${UPDATE_STATUS}"

echo "==== 7. Codex Audit Optimization: Updating app.conf with Public Origin ===="
APP_CONF_PATH="$(dirname "$0")/conf/app.conf"
if [ -f "$APP_CONF_PATH" ]; then
    echo "Updating origin in $APP_CONF_PATH to $CASDOOR_PUBLIC_ENDPOINT..."
    # 使用 sed 替换 origin 和 frontendBaseUrl
    sed -i "s|origin = .*|origin = \"$CASDOOR_PUBLIC_ENDPOINT\"|g" "$APP_CONF_PATH"
    sed -i "s|frontendBaseUrl = .*|frontendBaseUrl = \"$CASDOOR_PUBLIC_ENDPOINT\"|g" "$APP_CONF_PATH"
    echo "Note: You might need to restart the Casdoor container for app.conf changes to take effect."
else
    echo "Warning: app.conf not found at $APP_CONF_PATH. Skipping origin update."
fi

# Final output: print Client ID and Secret for environment setup
FINAL_APP_JSON=$(curl -s -b "${COOKIE_FILE}" "${CASDOOR_ENDPOINT}/api/get-application?id=admin/${APPLICATION}" | jq '.data')
CID=$(echo "${FINAL_APP_JSON}" | jq -r '.clientId')
CSEC=$(echo "${FINAL_APP_JSON}" | jq -r '.clientSecret')

echo "--------------------------------------------------"
echo "Setup Complete!"
echo "Organization: $ORGANIZATION"
echo "Application:  $APPLICATION"
echo "Client ID:    $CID"
echo "Client Secret: $CSEC"
echo "--------------------------------------------------"
echo "Please update your start_with_casdoor.sh or environment variables with these values."

# Export variables to a file for restart.sh to consume
ENV_FILE="$(dirname "$0")/.casdoor.env"
cat > "${ENV_FILE}" <<EOF
export CASDOOR_CLIENT_ID="${CID}"
export CASDOOR_CLIENT_SECRET="${CSEC}"
export CASDOOR_ORGANIZATION="${ORGANIZATION}"
export CASDOOR_APPLICATION="${APPLICATION}"
export CASDOOR_ADMIN_USER="${ADMIN_NAME}"
export CASDOOR_ADMIN_PASSWORD="${ADMIN_PASSWORD}"
EOF
echo "Credentials saved to ${ENV_FILE}"

echo "==== 8. Refreshing JWT verification certificate ===="
refresh_casdoor_jwt_cert

rm "${COOKIE_FILE}"
