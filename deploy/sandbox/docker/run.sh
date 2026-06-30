#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"

CONTAINER_NAME="${AIO_CONTAINER_NAME:-aio-yr}"
HOST_PORT="${AIO_PORT:-38888}"
IMAGE_NAME="${AIO_IMAGE_NAME:-aio-yr:latest}"

cd "${ROOT_DIR}"

AIO_CONTAINER_NAME="${CONTAINER_NAME}" \
AIO_PORT="${HOST_PORT}" \
AIO_IMAGE_NAME="${IMAGE_NAME}" \
docker compose -f "${COMPOSE_FILE}" up -d || { echo "Failed to start aio-yr" >&2; exit 1; }

echo "aio-yr started"
echo "Container: ${CONTAINER_NAME}"
echo "URL: http://127.0.0.1:${HOST_PORT}/terminal"
