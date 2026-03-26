#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

CONTAINER_NAME="${AIO_CONTAINER_NAME:-aio-yr}"
HOST_PORT="${AIO_PORT:-38888}"
IMAGE_NAME="${AIO_IMAGE_NAME:-aio-yr:latest}"

cd "${ROOT_DIR}"

docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

docker run -d \
  --name "${CONTAINER_NAME}" \
  --privileged \
  --cgroupns=host \
  -p "${HOST_PORT}:8888" \
  "${IMAGE_NAME}"

echo "aio-yr started"
echo "Container: ${CONTAINER_NAME}"
echo "URL: https://127.0.0.1:${HOST_PORT}/terminal"
