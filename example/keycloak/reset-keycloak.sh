#!/bin/bash
# Reset local Keycloak data and optionally reinitialize the yuanrong realm.
# Usage: ./reset-keycloak.sh [--force] [--no-start] [--no-init]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEYCLOAK_DATA_DIR="${SCRIPT_DIR}/data"
KEYCLOAK_ENV_FILE="${SCRIPT_DIR}/.keycloak.env"

FORCE=0
START_AFTER_RESET=1
INIT_AFTER_RESET=1

for arg in "$@"; do
    case "$arg" in
        --force)
            FORCE=1
            ;;
        --no-start)
            START_AFTER_RESET=0
            INIT_AFTER_RESET=0
            ;;
        --no-init)
            INIT_AFTER_RESET=0
            ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: $0 [--force] [--no-start] [--no-init]"
            exit 1
            ;;
    esac
done

if [ "$FORCE" -ne 1 ]; then
    echo "This will delete local Keycloak data, realm configuration, users, and client secrets."
    read -r -p "Continue? [y/N] " answer
    if [[ ! "$answer" =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
fi

echo "Stopping Keycloak..."
docker compose -f "${SCRIPT_DIR}/docker-compose.yml" down >/dev/null 2>&1 || true

if docker ps -a --format '{{.Names}}' | grep -q '^yr-keycloak$'; then
    docker rm -f yr-keycloak >/dev/null 2>&1 || true
fi

echo "Removing persisted data..."
rm -rf "${KEYCLOAK_DATA_DIR}"
rm -f "${KEYCLOAK_ENV_FILE}"
mkdir -p "${KEYCLOAK_DATA_DIR}/data"

echo "Reset complete."

if [ "$START_AFTER_RESET" -eq 1 ]; then
    echo "Starting fresh Keycloak..."
    "${SCRIPT_DIR}/start-keycloak.sh" start
fi

if [ "$INIT_AFTER_RESET" -eq 1 ]; then
    echo "Reinitializing realm, client, and demo users..."
    "${SCRIPT_DIR}/init-realm.sh"
fi
