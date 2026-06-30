#!/bin/bash
# Test Keycloak authentication flow
# Usage: ./test-auth.sh [token-exchange|verify|all]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080}"
REALM="yuanrong"
CLIENT_ID="frontend"
CLIENT_SECRET="${CLIENT_SECRET:-}"

# Default test user credentials
TEST_USER="${TEST_USER:-testuser}"
TEST_PASSWORD="${TEST_PASSWORD:-test123}"

# Frontend and iam-server endpoints
FRONTEND_URL="${FRONTEND_URL:-http://localhost:8889}"
IAM_SERVER_URL="${IAM_SERVER_URL:-http://localhost:8890}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

check_keycloak() {
    log_info "Checking Keycloak availability..."

    if curl -s "${KEYCLOAK_URL}/realms/${REALM}" > /dev/null 2>&1; then
        log_info "Keycloak is running at ${KEYCLOAK_URL}"
        return 0
    else
        log_error "Keycloak is not running. Start it with: ./start-keycloak.sh start"
        return 1
    fi
}

get_keycloak_token() {
    log_info "Getting Keycloak token for user '${TEST_USER}'..."

    RESPONSE=$(curl -s -X POST "${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "grant_type=password" \
        -d "client_id=${CLIENT_ID}" \
        -d "client_secret=${CLIENT_SECRET}" \
        -d "username=${TEST_USER}" \
        -d "password=${TEST_PASSWORD}" \
        -d "scope=openid profile email")

    ACCESS_TOKEN=$(echo "$RESPONSE" | jq -r '.access_token // empty')
    ID_TOKEN=$(echo "$RESPONSE" | jq -r '.id_token // empty')
    REFRESH_TOKEN=$(echo "$RESPONSE" | jq -r '.refresh_token // empty')
    ERROR=$(echo "$RESPONSE" | jq -r '.error_description // .error // empty')

    if [ -z "$ACCESS_TOKEN" ]; then
        log_error "Failed to get token: ${ERROR}"
        return 1
    fi

    log_info "Successfully obtained tokens"
    echo "ID_TOKEN=${ID_TOKEN}"
    echo "ACCESS_TOKEN=${ACCESS_TOKEN}"

    # Decode and display token info
    log_info "Token payload:"
    echo "$ID_TOKEN" | cut -d'.' -f2 | base64 -d 2>/dev/null | jq '.' 2>/dev/null || echo "(could not decode)"
}

test_token_exchange() {
    log_info "Testing token exchange with iam-server..."

    if [ -z "$ID_TOKEN" ]; then
        log_error "No ID token available. Run get_keycloak_token first."
        return 1
    fi

    # Test token exchange endpoint
    log_info "Calling iam-server token exchange endpoint..."

    EXPIRES_IN=7200  # 2 hours

    RESPONSE=$(curl -s -X POST "${IAM_SERVER_URL}/iam-server/v1/token/exchange" \
        -H "Content-Type: application/json" \
        -d "{\"id_token\": \"${ID_TOKEN}\", \"expires_in\": ${EXPIRES_IN}}")

    IAM_TOKEN=$(echo "$RESPONSE" | jq -r '.token // empty')
    TENANT_ID=$(echo "$RESPONSE" | jq -r '.tenant_id // empty')
    ERROR=$(echo "$RESPONSE" | jq -r '.error // empty')

    if [ -z "$IAM_TOKEN" ]; then
        log_error "Token exchange failed: ${ERROR}"
        log_error "Response: ${RESPONSE}"
        return 1
    fi

    log_info "Successfully exchanged token!"
    log_info "Tenant ID: ${TENANT_ID}"
    log_info "IAM Token: ${IAM_TOKEN:0:50}..."

    # Decode IAM token
    log_info "IAM Token payload:"
    echo "$IAM_TOKEN" | cut -d'.' -f2 | base64 -d 2>/dev/null | jq '.' 2>/dev/null || echo "(could not decode)"
}

test_frontend_auth() {
    log_info "Testing frontend authentication endpoints..."

    # Test login redirect
    log_info "Testing /auth/login redirect..."

    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -L --max-redirs 0 \
        "${FRONTEND_URL}/auth/login" 2>/dev/null || true)

    if [ "$HTTP_CODE" = "302" ] || [ "$HTTP_CODE" = "307" ]; then
        log_info "Login redirect works (HTTP ${HTTP_CODE})"
    else
        log_warn "Login redirect returned HTTP ${HTTP_CODE}"
    fi

    # Test user endpoint without auth
    log_info "Testing /auth/user without auth..."
    RESPONSE=$(curl -s "${FRONTEND_URL}/auth/user")
    echo "Response: ${RESPONSE}"
}

test_full_flow() {
    log_info "=== Testing Full Authentication Flow ==="
    echo ""

    # Step 1: Check Keycloak
    check_keycloak || return 1
    echo ""

    # Step 2: Get Keycloak token
    get_keycloak_token
    echo ""

    # Step 3: Test token exchange
    test_token_exchange
    echo ""

    # Step 4: Test frontend endpoints
    test_frontend_auth
    echo ""

    log_info "=== All tests completed ==="
}

# Main
case "${1:-all}" in
    check)
        check_keycloak
        ;;
    token)
        get_keycloak_token
        ;;
    exchange)
        get_keycloak_token
        test_token_exchange
        ;;
    frontend)
        test_frontend_auth
        ;;
    all|*)
        test_full_flow
        ;;
esac
