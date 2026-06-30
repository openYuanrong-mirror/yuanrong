#!/usr/bin/env bash
# Start Traefik as a reverse proxy for frontend and Keycloak
# Usage: ./traefik-start.sh [start|stop|status]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRAEFIK_PORT="${TRAEFIK_PORT:-80}"

start_traefik() {
    echo "Starting Traefik..."
    docker compose -f "${SCRIPT_DIR}/docker-compose.yml" up -d

    echo ""
    echo "  Frontend:  http://localhost:${TRAEFIK_PORT}/"
    echo "  Keycloak:  http://localhost:${TRAEFIK_PORT}/realms (API)"
    echo "  Keycloak Admin Console (direct): http://localhost:8080/admin"
    echo ""
    echo "Set KEYCLOAK_URL=http://localhost:${TRAEFIK_PORT} in restart.sh to use Traefik"
}

stop_traefik() {
    echo "Stopping Traefik..."
    docker compose -f "${SCRIPT_DIR}/docker-compose.yml" down
}

status_traefik() {
    docker compose -f "${SCRIPT_DIR}/docker-compose.yml" ps
}

case "${1:-start}" in
    start)   start_traefik ;;
    stop)    stop_traefik ;;
    status)  status_traefik ;;
    restart) stop_traefik; start_traefik ;;
    *)
        echo "Usage: $0 {start|stop|status|restart}"
        exit 1
        ;;
esac
