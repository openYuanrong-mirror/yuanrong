#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

CONDA_ENV_NAME="${YR_CONDA_ENV:-yr}"
PYTHON_BIN="${YR_HOST_PYTHON_BIN:-/home/wyc/.local/miniconda3/envs/${CONDA_ENV_NAME}/bin/python}"
SDK_WHEEL="${YR_SDK_WHEEL:-${ROOT_DIR}/output/openyuanrong_sdk-0.7.0.dev0-cp39-cp39-manylinux_2_34_x86_64.whl}"
SERVER_ADDRESS="${YR_HOST_SERVER_ADDRESS:-127.0.0.1:38888}"
ENABLE_TLS="${YR_HOST_ENABLE_TLS:-true}"
VERIFY_FILE_PATH="${YR_HOST_VERIFY_FILE:-}"
SANDBOX_NAME="${1:-$(python3 - <<'PY'
import uuid
print(uuid.uuid4())
PY
)}"
SANDBOX_NAMESPACE="${2:-sandbox}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "python not found: ${PYTHON_BIN}" >&2
  echo "Set YR_HOST_PYTHON_BIN or YR_CONDA_ENV to a Python 3.9 environment." >&2
  exit 1
fi

if [[ ! -f "${SDK_WHEEL}" ]]; then
  echo "sdk wheel not found: ${SDK_WHEEL}" >&2
  echo "Run 'make all' first, or set YR_SDK_WHEEL explicitly." >&2
  exit 1
fi

"${PYTHON_BIN}" -m pip install --quiet --force-reinstall "${SDK_WHEEL}"

YR_HOST_SERVER_ADDRESS="${SERVER_ADDRESS}" \
YR_HOST_ENABLE_TLS="${ENABLE_TLS}" \
YR_HOST_VERIFY_FILE="${VERIFY_FILE_PATH}" \
YR_SANDBOX_NAME="${SANDBOX_NAME}" \
YR_SANDBOX_NAMESPACE="${SANDBOX_NAMESPACE}" \
"${PYTHON_BIN}" - <<'PY'
import os

import yr

cfg = yr.Config()
cfg.server_address = os.environ["YR_HOST_SERVER_ADDRESS"]
cfg.in_cluster = False
cfg.enable_tls = os.environ["YR_HOST_ENABLE_TLS"].lower() == "true"
cfg.verify_file_path = os.environ.get("YR_HOST_VERIFY_FILE", "")

print(f"yr.init server_address={cfg.server_address} in_cluster={cfg.in_cluster} enable_tls={cfg.enable_tls}")
yr.init(cfg)

try:
    sandbox = yr.sandbox.SandBox()
    instance_name = yr.get(sandbox._instance.get_name.invoke())
    print(f"sandbox created, requested_name={os.environ['YR_SANDBOX_NAME']}, instance_name={instance_name}, namespace={os.environ['YR_SANDBOX_NAMESPACE']}")
finally:
    try:
        yr.finalize()
    except Exception:
        pass
PY
