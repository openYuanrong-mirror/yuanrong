#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

CONDA_ENV_NAME="${YR_CONDA_ENV:-yr}"
PYTHON_BIN="${YR_HOST_PYTHON_BIN:-/home/wyc/.local/miniconda3/envs/${CONDA_ENV_NAME}/bin/python}"
SDK_WHEEL="${YR_SDK_WHEEL:-${ROOT_DIR}/output/openyuanrong_sdk-0.7.0.dev0-cp39-cp39-manylinux_2_34_x86_64.whl}"
SERVER_ADDRESS="${YR_HOST_SERVER_ADDRESS:-127.0.0.1:38888}"
VERIFY_FILE_PATH="${YR_HOST_VERIFY_FILE:-}"
FORWARD_PORT="${YR_FORWARD_PORT:-8080}"

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
YR_HOST_VERIFY_FILE="${VERIFY_FILE_PATH}" \
YR_FORWARD_PORT="${FORWARD_PORT}" \
"${PYTHON_BIN}" - <<'PY'
import os
import subprocess
import time

import yr
from yr.config import PortForwarding
from yr.sandbox.sandbox import SandBoxInstance, _build_gateway_url


cfg = yr.Config()
cfg.server_address = os.environ["YR_HOST_SERVER_ADDRESS"]
cfg.in_cluster = False
cfg.enable_tls = False
cfg.verify_file_path = os.environ.get("YR_HOST_VERIFY_FILE", "")
yr.init(cfg)

instance = None
instance_id = ""
port = int(os.environ["YR_FORWARD_PORT"])

try:
    opt = yr.InvokeOptions()
    opt.custom_extensions["lifecycle"] = "detached"
    opt.idle_timeout = 3600
    opt.skip_serialize = True
    opt.port_forwardings = [PortForwarding(port=port)]

    instance = SandBoxInstance.options(opt).invoke()
    instance_id = yr.get(instance.get_name.invoke())
    url = _build_gateway_url(instance_id, port, cfg.server_address)

    print(f"instance_id={instance_id}")
    print(f"url={url}")

    yr.get(
        instance.execute.invoke(
            f"nohup python3 -m http.server {port} --bind 0.0.0.0 >/tmp/pf-http.log 2>&1 </dev/null & sleep 1",
            20,
        )
    )

    time.sleep(3)

    proc = subprocess.run(
        ["curl", "-sk", "-o", "-", "-w", "\nHTTP_STATUS:%{http_code}\n", url],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    print(proc.stdout, end="")
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
    if "HTTP_STATUS:200" not in proc.stdout:
        raise SystemExit(1)
finally:
    if instance_id:
        try:
            yr.kill_instance(instance_id)
        except Exception:
            pass
    try:
        yr.finalize()
    except Exception:
        pass
PY
