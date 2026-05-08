#!/usr/bin/env bash
set -euo pipefail

umask 0027

helper_script="${YR_CONTROLPLANE_HELPER_DIR:-/home/sn/bin/alias}/control_plane_alias.sh"
if [ -f "${helper_script}" ]; then
    bash "${helper_script}" "function_master"
fi

master_ip="${RUNTIME_POD_IP:-$(hostname -i | awk '{print $1}')}"
etcd_addr_list="${YR_ETCD_ADDR_LIST:?Set YR_ETCD_ADDR_LIST for external etcd, e.g. host1:2379,host2:2379}"
services_path="${YR_SERVICES_PATH:-/home/sn/service-config/services.yaml}"
controlplane_cpu_num="${YR_CONTROLPLANE_CPU_NUM:-100}"

exec /usr/local/bin/yr start \
  --master \
  --block true \
  -e \
  --port_policy FIX \
  --etcd_mode outter \
  --etcd_addr_list "${etcd_addr_list}" \
  --enable_function_scheduler true \
  --enable_meta_service true \
  --enable_iam_server true \
  --cpu_num "${controlplane_cpu_num}" \
  -a "${master_ip}" \
  -p "${services_path}" \
  "$@"
