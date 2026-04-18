#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
required_files=(
    "${SCRIPT_DIR}/pkg/runtime-launcher"
)

for required_file in "${required_files[@]}"; do
    if [ ! -e "${required_file}" ]; then
        echo "Missing required build artifact: ${required_file}" >&2
        echo "Run: make all" >&2
        exit 1
    fi
done

if ! compgen -G "${SCRIPT_DIR}/pkg/openyuanrong-*.whl" >/dev/null; then
    echo "Missing required build artifact: ${SCRIPT_DIR}/pkg/openyuanrong-*.whl" >&2
    echo "Run: make all" >&2
    exit 1
fi

if ! compgen -G "${SCRIPT_DIR}/pkg/openyuanrong_sdk*.whl" >/dev/null; then
    echo "Missing required build artifact: ${SCRIPT_DIR}/pkg/openyuanrong_sdk-*.whl" >&2
    echo "Run: make all" >&2
    exit 1
fi

docker build -f "${SCRIPT_DIR}/Dockerfile.runtime" -t aio-yr-runtime:latest "${SCRIPT_DIR}"
docker save aio-yr-runtime:latest -o "${SCRIPT_DIR}/pkg/aio-yr-runtime.tar"
docker build -f "${SCRIPT_DIR}/Dockerfile.aio-yr" -t aio-yr:latest "${SCRIPT_DIR}"
