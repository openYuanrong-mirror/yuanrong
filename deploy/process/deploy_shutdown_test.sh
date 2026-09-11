#!/usr/bin/env bash
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# Licensed under the Apache License, Version 2.0.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT
awk '/^function exit_all_processes/{copy=1} copy && /^function prepare_log_rotate/{exit} copy{print}' \
  "$script_dir/deploy.sh" > "$test_dir/shutdown.sh"

cat > "$test_dir/case.sh" <<'CASE'
set -u
declare -A pid_table=([function_proxy]=301 [function_master]=302 [ds_worker]=303 [foreign]=304)
master_alive=true
data_alive=true
log_info() { :; }
need_health_check() { [[ "$1" != function_proxy || "$MODE" != shared ]]; }
is_child_process() { [[ "$1" != 304 ]]; }
terminate_process() {
  case "$1" in
    301) [[ "$master_alive" == true && "$data_alive" == true ]] || exit 42 ;;
    302) master_alive=false ;;
    303) data_alive=false ;;
    *) exit 43 ;;
  esac
  echo "$1" >> "$OUT"
}
source "$SCRIPT"
exit_all_processes
CASE

for mode in owned shared; do
  result=0
  MODE="$mode" OUT="$test_dir/$mode.out" SCRIPT="$test_dir/shutdown.sh" \
    bash "$test_dir/case.sh" || result=$?
  [[ "$result" == 1 ]] || { echo "Shutdown failed ($mode): $result"; exit 1; }
  [[ $(grep -c '^302$' "$test_dir/$mode.out") == 1 ]]
  [[ $(grep -c '^303$' "$test_dir/$mode.out") == 1 ]]
  if [[ "$mode" == owned ]]; then
    [[ $(head -1 "$test_dir/$mode.out") == 301 ]]
    [[ $(grep -c '^301$' "$test_dir/$mode.out") == 1 ]]
  else
    ! grep -q '^301$' "$test_dir/$mode.out"
  fi
done
echo 'DEPLOY_SHUTDOWN_ORDER_PASS'
