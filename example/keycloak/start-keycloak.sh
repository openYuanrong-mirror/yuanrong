#!/bin/bash
# Start Keycloak for local development/testing
# Usage: ./start-keycloak.sh [start|stop|status]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEYCLOAK_DATA="${SCRIPT_DIR}/data"
KEYCLOAK_LOG="/tmp/yr_sessions/keycloak.log"
KEYCLOAK_CONTAINER="yr-keycloak"

KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080}"
# Public URL seen by the browser (i.e. through reverse proxy)
KEYCLOAK_PUBLIC_URL="${KEYCLOAK_PUBLIC_URL:-${KEYCLOAK_URL}}"
KEYCLOAK_ADMIN="${KEYCLOAK_ADMIN:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin123}"

start_keycloak() {
    # Check if already running
    if docker ps --format '{{.Names}}' | grep -q "^${KEYCLOAK_CONTAINER}$"; then
        echo "Keycloak is already running"
        echo "URL: ${KEYCLOAK_URL}"
        echo "Admin: ${KEYCLOAK_ADMIN} / ${KEYCLOAK_ADMIN_PASSWORD}"
        return 0
    fi

    # 确保共享网络存在
    docker network inspect yr-net >/dev/null 2>&1 || docker network create yr-net

    # Create data directory
    mkdir -p "${KEYCLOAK_DATA}"
    mkdir -p "${KEYCLOAK_DATA}/data"

    echo "Starting Keycloak via docker compose..."
    KEYCLOAK_PUBLIC_URL="${KEYCLOAK_PUBLIC_URL}" \
    KEYCLOAK_ADMIN="${KEYCLOAK_ADMIN}" \
    KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD}" \
    docker compose -f "${SCRIPT_DIR}/docker-compose.yml" up -d

    echo "Waiting for Keycloak to start..."
    for i in {1..30}; do
        if curl -s "${KEYCLOAK_URL}/realms/master" > /dev/null 2>&1; then
            echo "Keycloak is ready!"
            echo "URL: ${KEYCLOAK_URL}"
            echo "Admin Console: ${KEYCLOAK_URL}/admin"
            echo "Admin: ${KEYCLOAK_ADMIN} / ${KEYCLOAK_ADMIN_PASSWORD}"
            return 0
        fi
        sleep 1
    done

    echo "Keycloak failed to start within 30 seconds"
    return 1
}

stop_keycloak() {
    echo "Stopping Keycloak..."
    docker compose -f "${SCRIPT_DIR}/docker-compose.yml" down
    echo "Keycloak stopped"
}

status_keycloak() {
    if docker ps --format '{{.Names}}' | grep -q "^${KEYCLOAK_CONTAINER}$"; then
        echo "Keycloak is running"
        echo "URL: ${KEYCLOAK_URL}"
        echo "Admin Console: ${KEYCLOAK_URL}/admin"
        return 0
    else
        echo "Keycloak is not running"
        return 1
    fi
}

case "${1:-start}" in
    start)
        start_keycloak
        ;;
    stop)
        stop_keycloak
        ;;
    status)
        status_keycloak
        ;;
    restart)
        stop_keycloak
        start_keycloak
        ;;
    *)
        echo "Usage: $0 {start|stop|status|restart}"
        exit 1
        ;;
esac
