#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

CONDA_ENV_NAME="${YR_CONDA_ENV:-yr}"
PYTHON_BIN="${YR_HOST_PYTHON_BIN:-/home/wyc/.local/miniconda3/envs/${CONDA_ENV_NAME}/bin/python}"
SDK_WHEEL="${YR_SDK_WHEEL:-${ROOT_DIR}/output/openyuanrong_sdk-0.7.0.dev0-cp39-cp39-manylinux_2_34_x86_64.whl}"
SERVER_ADDRESS="${YR_HOST_SERVER_ADDRESS:-127.0.0.1:38888}"
VERIFY_FILE_PATH="${YR_HOST_VERIFY_FILE:-}"
UPSTREAM_PORT="${YR_TUNNEL_UPSTREAM_PORT:-19080}"
PROXY_PORT="${YR_TUNNEL_PROXY_PORT:-8766}"

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

HTTP_PID=""
cleanup() {
  if [[ -n "${HTTP_PID}" ]]; then
    kill "${HTTP_PID}" >/dev/null 2>&1 || true
    wait "${HTTP_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

"${PYTHON_BIN}" -m pip install --quiet --force-reinstall "${SDK_WHEEL}"

"${PYTHON_BIN}" -m http.server "${UPSTREAM_PORT}" --bind 127.0.0.1 >/tmp/verify-tunnel-host-http.log 2>&1 &
HTTP_PID=$!
sleep 1

if ! curl -sf "http://127.0.0.1:${UPSTREAM_PORT}/" >/dev/null; then
  echo "local upstream did not start on 127.0.0.1:${UPSTREAM_PORT}" >&2
  exit 1
fi

YR_HOST_SERVER_ADDRESS="${SERVER_ADDRESS}" \
YR_HOST_VERIFY_FILE="${VERIFY_FILE_PATH}" \
YR_TUNNEL_UPSTREAM_PORT="${UPSTREAM_PORT}" \
YR_TUNNEL_PROXY_PORT="${PROXY_PORT}" \
YR_SERVER_ADDRESS="${SERVER_ADDRESS}" \
YR_GATEWAY_ADDRESS="${SERVER_ADDRESS}" \
"${PYTHON_BIN}" - <<'PY'
import os

import yr

cfg = yr.Config()
cfg.server_address = os.environ["YR_HOST_SERVER_ADDRESS"]
cfg.in_cluster = False
cfg.enable_tls = False
cfg.verify_file_path = os.environ.get("YR_HOST_VERIFY_FILE", "")
yr.init(cfg)

sandbox = None
upstream_port = int(os.environ["YR_TUNNEL_UPSTREAM_PORT"])
proxy_port = int(os.environ["YR_TUNNEL_PROXY_PORT"])

try:
    sandbox = yr.sandbox.create(
        upstream=f"127.0.0.1:{upstream_port}",
        proxy_port=proxy_port,
    )
    print(f"tunnel_url={sandbox.get_tunnel_url()}")

    result = yr.get(
        sandbox.exec(
            "python3 - <<'INNER'\n"
            "import urllib.request\n"
            f"print(urllib.request.urlopen('http://127.0.0.1:{proxy_port}/', timeout=20).read(200).decode('utf-8', errors='replace'))\n"
            "INNER",
            60,
        )
    )

    print(f"returncode={result.get('returncode')}")
    print("stdout:")
    print(result.get("stdout", ""))
    print("stderr:")
    print(result.get("stderr", ""))

    if result.get("returncode") != 0:
        raise SystemExit(result.get("returncode"))
    if "Directory listing for" not in result.get("stdout", ""):
        raise SystemExit("tunnel verification failed: upstream response marker not found")
finally:
    if sandbox is not None:
        try:
            sandbox.terminate()
        except Exception as exc:
            print(f"terminate_error={exc!r}")
    try:
        yr.finalize()
    except Exception:
        pass
PY
