#!/bin/bash
# Initialize Keycloak realm and client for yuanrong
# Usage: ./init-realm.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

KEYCLOAK_URL="${KEYCLOAK_URL:-http://127.0.0.1:8080}"
KEYCLOAK_ADMIN="${KEYCLOAK_ADMIN:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin123}"
REGISTRATION_ALLOWED="${REGISTRATION_ALLOWED:-true}"

echo "=== Initializing Keycloak for yuanrong ==="
echo "Keycloak URL: ${KEYCLOAK_URL}"
echo "Registration Allowed: ${REGISTRATION_ALLOWED}"
echo ""

# Get admin access token
echo "Getting admin access token..."
ADMIN_TOKEN=$(curl -s -X POST "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=${KEYCLOAK_ADMIN}" \
    -d "password=${KEYCLOAK_ADMIN_PASSWORD}" \
    -d "grant_type=password" \
    -d "client_id=admin-cli" | jq -r '.access_token')

if [ -z "$ADMIN_TOKEN" ] || [ "$ADMIN_TOKEN" = "null" ]; then
    echo "Failed to get admin token. Check if Keycloak is running and credentials are correct."
    exit 1
fi

echo "Admin token obtained successfully"
echo ""

# Check if realm already exists
REALM_EXISTS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    "${KEYCLOAK_URL}/admin/realms/yuanrong")

if [ "$REALM_EXISTS" = "200" ]; then
    echo "Realm 'yuanrong' already exists. Skipping creation."
else
    echo "Creating realm 'yuanrong'..."

    # Create realm with minimal config (roles and client will be created separately)
    curl -s -X POST "${KEYCLOAK_URL}/admin/realms" \
        -H "Authorization: Bearer ${ADMIN_TOKEN}" \
        -H "Content-Type: application/json" \
        -d '{
            "realm": "yuanrong",
            "enabled": true,
            "sslRequired": "none",
            "registrationAllowed": '"${REGISTRATION_ALLOWED}"',
            "loginWithEmailAllowed": true,
            "bruteForceProtected": true
        }'

    echo "Realm created"
fi

echo ""

# Create roles
echo "Creating roles..."
for ROLE in admin developer user viewer; do
    curl -s -X POST "${KEYCLOAK_URL}/admin/realms/yuanrong/roles" \
        -H "Authorization: Bearer ${ADMIN_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"${ROLE}\"}" 2>/dev/null || echo "Role '${ROLE}' may already exist"
done
echo "Roles created"
echo ""

# Function to create frontend client
create_client() {
    curl -s -X POST "${KEYCLOAK_URL}/admin/realms/yuanrong/clients" \
        -H "Authorization: Bearer ${ADMIN_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{
            \"clientId\": \"frontend\",
            \"name\": \"Frontend Client\",
            \"enabled\": true,
            \"clientAuthenticatorType\": \"client-secret\",
            \"secret\": \"${CLIENT_SECRET}\",
            \"redirectUris\": [\"http://localhost:*\", \"http://127.0.0.1:*\", \"*\"],
            \"webOrigins\": [\"http://localhost:*\", \"http://127.0.0.1:*\", \"*\"],
            \"standardFlowEnabled\": true,
            \"implicitFlowEnabled\": false,
            \"directAccessGrantsEnabled\": true,
            \"publicClient\": false,
            \"protocol\": \"openid-connect\"
        }"
    echo "Client 'frontend' created"
}

# Create frontend client
echo "Creating frontend client..."

# Generate a random client secret
CLIENT_SECRET="${CLIENT_SECRET:-$(openssl rand -hex 16)}"
echo "Client Secret: ${CLIENT_SECRET}"

CLIENT_EXISTS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    "${KEYCLOAK_URL}/admin/realms/yuanrong/clients?clientId=frontend")

if [ "$CLIENT_EXISTS" = "200" ]; then
    # Check if client actually exists in response
    CLIENT_ID=$(curl -s -H "Authorization: Bearer ${ADMIN_TOKEN}" \
        "${KEYCLOAK_URL}/admin/realms/yuanrong/clients?clientId=frontend" | jq -r '.[0].id // empty')

    if [ -n "$CLIENT_ID" ]; then
        echo "Client 'frontend' already exists with ID: ${CLIENT_ID}"
        echo "Updating client secret..."

        # Update client with new secret
        curl -s -X PUT "${KEYCLOAK_URL}/admin/realms/yuanrong/clients/${CLIENT_ID}" \
            -H "Authorization: Bearer ${ADMIN_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "{
                \"clientId\": \"frontend\",
                \"name\": \"Frontend Client\",
                \"enabled\": true,
                \"clientAuthenticatorType\": \"client-secret\",
                \"secret\": \"${CLIENT_SECRET}\",
                \"redirectUris\": [\"http://localhost:*\", \"http://127.0.0.1:*\", \"*\"],
                \"webOrigins\": [\"http://localhost:*\", \"http://127.0.0.1:*\", \"*\"],
                \"standardFlowEnabled\": true,
                \"implicitFlowEnabled\": false,
                \"directAccessGrantsEnabled\": true,
                \"publicClient\": false,
                \"protocol\": \"openid-connect\"
            }"
        echo "Client secret updated"
    else
        create_client
    fi
else
    create_client
fi

echo ""

# Ensure realm roles are included in ID Token
# By default Keycloak only puts realm_access into the access token.
# We need a client-level protocol mapper to also add it to the ID token.
echo "Configuring realm roles mapper for ID Token..."

if [ -z "$CLIENT_ID" ]; then
    CLIENT_ID=$(curl -s -H "Authorization: Bearer ${ADMIN_TOKEN}" \
        "${KEYCLOAK_URL}/admin/realms/yuanrong/clients?clientId=frontend" | jq -r '.[0].id // empty')
fi

if [ -n "$CLIENT_ID" ]; then
    # Check if mapper already exists
    MAPPER_EXISTS=$(curl -s -H "Authorization: Bearer ${ADMIN_TOKEN}" \
        "${KEYCLOAK_URL}/admin/realms/yuanrong/clients/${CLIENT_ID}/protocol-mappers/models" \
        | jq -r '.[] | select(.name == "realm roles for id_token") | .id // empty')

    if [ -n "$MAPPER_EXISTS" ]; then
        echo "Realm roles ID Token mapper already exists, updating..."
        curl -s -X PUT "${KEYCLOAK_URL}/admin/realms/yuanrong/clients/${CLIENT_ID}/protocol-mappers/models/${MAPPER_EXISTS}" \
            -H "Authorization: Bearer ${ADMIN_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "{
                \"id\": \"${MAPPER_EXISTS}\",
                \"name\": \"realm roles for id_token\",
                \"protocol\": \"openid-connect\",
                \"protocolMapper\": \"oidc-usermodel-realm-role-mapper\",
                \"config\": {
                    \"multivalued\": \"true\",
                    \"claim.name\": \"realm_access.roles\",
                    \"jsonType.label\": \"String\",
                    \"id.token.claim\": \"true\",
                    \"access.token.claim\": \"true\",
                    \"userinfo.token.claim\": \"true\"
                }
            }"
    else
        echo "Creating realm roles ID Token mapper..."
        curl -s -X POST "${KEYCLOAK_URL}/admin/realms/yuanrong/clients/${CLIENT_ID}/protocol-mappers/models" \
            -H "Authorization: Bearer ${ADMIN_TOKEN}" \
            -H "Content-Type: application/json" \
            -d '{
                "name": "realm roles for id_token",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-usermodel-realm-role-mapper",
                "config": {
                    "multivalued": "true",
                    "claim.name": "realm_access.roles",
                    "jsonType.label": "String",
                    "id.token.claim": "true",
                    "access.token.claim": "true",
                    "userinfo.token.claim": "true"
                }
            }'
    fi
    echo "Realm roles mapper configured"

    # Add user attribute mappers for cpu_quota and mem_quota
    for ATTR in cpu_quota mem_quota; do
        MAPPER_NAME="${ATTR} mapper"
        EXISTING=$(curl -s -H "Authorization: Bearer ${ADMIN_TOKEN}" \
            "${KEYCLOAK_URL}/admin/realms/yuanrong/clients/${CLIENT_ID}/protocol-mappers/models" \
            | jq -r --arg name "$MAPPER_NAME" '.[] | select(.name == $name) | .id // empty')

        if [ -n "$EXISTING" ]; then
            echo "Mapper '${MAPPER_NAME}' already exists, updating..."
            curl -s -X PUT "${KEYCLOAK_URL}/admin/realms/yuanrong/clients/${CLIENT_ID}/protocol-mappers/models/${EXISTING}" \
                -H "Authorization: Bearer ${ADMIN_TOKEN}" \
                -H "Content-Type: application/json" \
                -d "{
                    \"id\": \"${EXISTING}\",
                    \"name\": \"${MAPPER_NAME}\",
                    \"protocol\": \"openid-connect\",
                    \"protocolMapper\": \"oidc-usermodel-attribute-mapper\",
                    \"config\": {
                        \"user.attribute\": \"${ATTR}\",
                        \"claim.name\": \"${ATTR}\",
                        \"jsonType.label\": \"long\",
                        \"id.token.claim\": \"true\",
                        \"access.token.claim\": \"true\",
                        \"userinfo.token.claim\": \"true\"
                    }
                }"
        else
            echo "Creating mapper '${MAPPER_NAME}'..."
            curl -s -X POST "${KEYCLOAK_URL}/admin/realms/yuanrong/clients/${CLIENT_ID}/protocol-mappers/models" \
                -H "Authorization: Bearer ${ADMIN_TOKEN}" \
                -H "Content-Type: application/json" \
                -d "{
                    \"name\": \"${MAPPER_NAME}\",
                    \"protocol\": \"openid-connect\",
                    \"protocolMapper\": \"oidc-usermodel-attribute-mapper\",
                    \"config\": {
                        \"user.attribute\": \"${ATTR}\",
                        \"claim.name\": \"${ATTR}\",
                        \"jsonType.label\": \"long\",
                        \"id.token.claim\": \"true\",
                        \"access.token.claim\": \"true\",
                        \"userinfo.token.claim\": \"true\"
                    }
                }"
        fi
        echo "Mapper '${MAPPER_NAME}' configured"
    done
else
    echo "WARNING: Could not find frontend client ID, skipping mapper configuration"
fi

echo ""

# Function to create user and assign role
# Usage: create_user <username> <email> <password> <role> <cpu_quota> <mem_quota> <first_name> <last_name>
create_user() {
    local USERNAME=$1
    local EMAIL=$2
    local PASSWORD=$3
    local ROLE=$4
    local CPU_QUOTA=$5
    local MEM_QUOTA=$6
    local FIRST_NAME=$7
    local LAST_NAME=$8

    USER_ID=$(curl -s -X POST "${KEYCLOAK_URL}/admin/realms/yuanrong/users" \
        -H "Authorization: Bearer ${ADMIN_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{
            \"username\": \"${USERNAME}\",
            \"enabled\": true,
            \"emailVerified\": true,
            \"email\": \"${EMAIL}\",
            \"firstName\": \"${FIRST_NAME}\",
            \"lastName\": \"${LAST_NAME}\",
            \"attributes\": {
                \"cpu_quota\": [\"${CPU_QUOTA}\"],
                \"mem_quota\": [\"${MEM_QUOTA}\"]
            },
            \"credentials\": [{\"type\": \"password\", \"value\": \"${PASSWORD}\", \"temporary\": false}]
        }" -w "%{http_code}" -o /tmp/user_response.txt)

    if [ "$USER_ID" = "201" ]; then
        USER_UUID=$(curl -s -H "Authorization: Bearer ${ADMIN_TOKEN}" \
            "${KEYCLOAK_URL}/admin/realms/yuanrong/users?username=${USERNAME}" | jq -r '.[0].id')
        echo "Created user: ${USERNAME}"
    else
        echo "User '${USERNAME}' already exists, repairing account state..."
        USER_UUID=$(curl -s -H "Authorization: Bearer ${ADMIN_TOKEN}" \
            "${KEYCLOAK_URL}/admin/realms/yuanrong/users?username=${USERNAME}" | jq -r '.[0].id // empty')
        if [ -n "$USER_UUID" ]; then
            curl -s -X PUT "${KEYCLOAK_URL}/admin/realms/yuanrong/users/${USER_UUID}" \
                -H "Authorization: Bearer ${ADMIN_TOKEN}" \
                -H "Content-Type: application/json" \
                -d "{
                    \"username\": \"${USERNAME}\",
                    \"enabled\": true,
                    \"emailVerified\": true,
                    \"email\": \"${EMAIL}\",
                    \"firstName\": \"${FIRST_NAME}\",
                    \"lastName\": \"${LAST_NAME}\",
                    \"requiredActions\": [],
                    \"attributes\": {
                        \"cpu_quota\": [\"${CPU_QUOTA}\"],
                        \"mem_quota\": [\"${MEM_QUOTA}\"]
                    }
                }"

            curl -s -X PUT "${KEYCLOAK_URL}/admin/realms/yuanrong/users/${USER_UUID}/reset-password" \
                -H "Authorization: Bearer ${ADMIN_TOKEN}" \
                -H "Content-Type: application/json" \
                -d "{
                    \"type\": \"password\",
                    \"value\": \"${PASSWORD}\",
                    \"temporary\": false
                }"

            EXISTING_ROLE_MAPPINGS=$(curl -s -H "Authorization: Bearer ${ADMIN_TOKEN}" \
                "${KEYCLOAK_URL}/admin/realms/yuanrong/users/${USER_UUID}/role-mappings/realm")
            if [ "${EXISTING_ROLE_MAPPINGS}" != "[]" ]; then
                curl -s -X DELETE "${KEYCLOAK_URL}/admin/realms/yuanrong/users/${USER_UUID}/role-mappings/realm" \
                    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
                    -H "Content-Type: application/json" \
                    -d "${EXISTING_ROLE_MAPPINGS}" >/dev/null
            fi
        fi
    fi

    if [ -n "${USER_UUID}" ]; then
        ROLE_ID=$(curl -s -H "Authorization: Bearer ${ADMIN_TOKEN}" \
            "${KEYCLOAK_URL}/admin/realms/yuanrong/roles/${ROLE}" | jq -r '.id')

        curl -s -X POST "${KEYCLOAK_URL}/admin/realms/yuanrong/users/${USER_UUID}/role-mappings/realm" \
            -H "Authorization: Bearer ${ADMIN_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "[{\"id\": \"${ROLE_ID}\", \"name\": \"${ROLE}\"}]" >/dev/null

        echo "Ensured user state: ${USERNAME} role=${ROLE} cpu_quota=${CPU_QUOTA} mem_quota=${MEM_QUOTA}"
    fi
}

# Create test users
# cpu_quota: millicores, mem_quota: MB
echo "Creating test users..."

create_user "testuser"  "test@yuanrong.local"  "test123"  "user"      "1000"  "1024"  "Test"      "User"
create_user "developer" "dev@yuanrong.local"   "dev123"   "developer" "4000"  "8192"  "Dev"       "User"
create_user "testadmin" "admin@yuanrong.local" "admin123" "admin"     "8000"  "16384" "Test"      "Admin"

echo ""
# 将 secret 持久化，供 restart.sh 使用
ENV_FILE="${SCRIPT_DIR}/.keycloak.env"
cat > "${ENV_FILE}" <<EOF
KEYCLOAK_CLIENT_SECRET=${CLIENT_SECRET}
EOF
chmod 600 "${ENV_FILE}"
echo "Client secret saved to ${ENV_FILE}"

echo "=== Keycloak initialization complete ==="
echo ""
echo "Configuration for frontend (config.toml):"
echo "----------------------------------------"
echo "[keycloakConfig]"
echo "url = \"${KEYCLOAK_URL}\""
echo "realm = \"yuanrong\""
echo "clientId = \"frontend\""
echo "clientSecret = \"${CLIENT_SECRET}\""
echo "enabled = true"
echo ""
echo "Configuration for iam-server (flags):"
echo "----------------------------------------"
echo "--keycloak_url=${KEYCLOAK_URL}"
echo "--keycloak_realm=yuanrong"
echo "--keycloak_enabled=true"
echo ""
echo "Test users:"
echo "----------------------------------------"
echo "  testuser / test123   (role: user)"
echo "  developer / dev123   (role: developer)"
echo "  testadmin / admin123 (role: admin)"
echo ""
echo "Admin Console: ${KEYCLOAK_URL}/admin"
echo "Admin credentials: ${KEYCLOAK_ADMIN} / ${KEYCLOAK_ADMIN_PASSWORD}"
echo "Registration Allowed: ${REGISTRATION_ALLOWED}"
