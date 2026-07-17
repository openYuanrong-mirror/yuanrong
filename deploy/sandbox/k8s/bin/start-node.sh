#!/usr/bin/env bash
set -euo pipefail

umask 0027

node_ip="${HOST_IP:-${RUNTIME_HOST_IP:-$(hostname -i | awk '{print $1}')}}"
master_host="${YR_MASTER_IP:?Set YR_MASTER_IP to the master service DNS name or IP}"
etcd_addr_list="${YR_ETCD_ADDR_LIST:?Set YR_ETCD_ADDR_LIST for external etcd, e.g. host1:2379,host2:2379}"
services_path="${YR_SERVICES_PATH:-/home/sn/service-config/services.yaml}"

resolve_ipv4() {
  local host="$1"
  if [[ "${host}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    printf '%s\n' "${host}"
    return 0
  fi
  if command -v getent >/dev/null 2>&1; then
    getent ahostsv4 "${host}" | awk 'NR == 1 {print $1}'
    return 0
  fi
  python3 -c 'import socket, sys; print(socket.gethostbyname(sys.argv[1]))' "${host}"
}

master_ip="$(resolve_ipv4 "${master_host}")"
if [ -z "${master_ip}" ]; then
  echo "failed to resolve YR_MASTER_IP=${master_host} to an IPv4 address" >&2
  exit 1
fi

exec /usr/local/bin/yr start \
  --block true \
  -e \
  --port_policy FIX \
  --etcd_mode outter \
  --etcd_addr_list "${etcd_addr_list}" \
  --enable_runtime_launcher true \
  --master_ip "${master_ip}" \
  -a "${node_ip}" \
  -p "${services_path}" \
  "$@"
