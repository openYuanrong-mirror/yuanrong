#!/usr/bin/env bash

set -euo pipefail

AIO_NODE_IP="$(hostname -i | awk '{print $1}')"
ETCD_ENDPOINT="${AIO_NODE_IP}:32379"
ETCDCTL_BIN="${ETCDCTL_BIN:-$(python - <<'PY'
import sysconfig
from pathlib import Path

etcdctl = Path(sysconfig.get_paths()["purelib"]) / "yr" / "inner" / "third_party" / "etcd" / "etcdctl"
print(etcdctl)
PY
)}"

for _ in $(seq 1 60); do
    if ETCDCTL_API=3 "${ETCDCTL_BIN}" --endpoints="${ETCD_ENDPOINT}" endpoint health >/dev/null 2>&1; then
        ETCDCTL_API=3 "${ETCDCTL_BIN}" --endpoints="${ETCD_ENDPOINT}" put traefik/_keepalive 1 >/dev/null
        exit 0
    fi
    sleep 1
done

echo "failed to seed traefik root key in etcd at ${ETCD_ENDPOINT}" >&2
exit 1
