#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
HELM_BIN="${HELM_BIN:-helm}"
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"

KUBECONFIG_PATH="${YR_K8S_KUBECONFIG:-${HOME}/.kube/beijing4.yaml}"
RELEASE_NAME="${YR_K8S_RELEASE:-yr-k8s}"
NAMESPACE="${YR_K8S_NAMESPACE:-yr}"
VALUES_FILE="${YR_K8S_VALUES_FILE:-${SCRIPT_DIR}/k8s/values.local.yaml}"
EXTRA_VALUES_FILE="${YR_K8S_EXTRA_VALUES_FILE:-}"

REGISTRY_SERVER="${YR_K8S_REGISTRY_SERVER:-swr.cn-southwest-2.myhuaweicloud.com}"
REGISTRY_REPO="${YR_K8S_REGISTRY_REPO:-swr.cn-southwest-2.myhuaweicloud.com/openyuanrong}"
IMAGE_TAG="${YR_K8S_IMAGE_TAG:?Set YR_K8S_IMAGE_TAG to the pushed image tag}"
RUNTIME_IMAGE_TAG="${YR_K8S_RUNTIME_IMAGE_TAG:-${IMAGE_TAG}}"
RUNTIME_IMAGE_TAG_CP39="${YR_K8S_RUNTIME_IMAGE_TAG_CP39:-${IMAGE_TAG}-cp39}"
RUNTIME_IMAGE_TAG_CP310="${YR_K8S_RUNTIME_IMAGE_TAG_CP310:-${RUNTIME_IMAGE_TAG}}"
RUNTIME_IMAGE_TAG_CP311="${YR_K8S_RUNTIME_IMAGE_TAG_CP311:-${IMAGE_TAG}-cp311}"
RUNTIME_IMAGE_TAG_CP312="${YR_K8S_RUNTIME_IMAGE_TAG_CP312:-${IMAGE_TAG}-cp312}"
RUNTIME_IMAGE_TAG_CP313="${YR_K8S_RUNTIME_IMAGE_TAG_CP313:-${IMAGE_TAG}-cp313}"
PULL_SECRET_NAME="${YR_K8S_PULL_SECRET_NAME:-yr-swr-pull}"

require_bin() {
  local bin_name="$1"
  if ! command -v "${bin_name}" >/dev/null 2>&1; then
    printf 'Missing required CLI: %s\n' "${bin_name}" >&2
    exit 1
  fi
}

validate_k8s_name() {
  local value="$1"
  local field_name="$2"
  if [[ ! "${value}" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
    printf '%s must be a Kubernetes DNS label, got: %s\n' "${field_name}" "${value}" >&2
    exit 1
  fi
}

create_namespace() {
  "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" create namespace "${NAMESPACE}" --dry-run=client -o yaml \
    | "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" apply -f -
}

create_or_update_pull_secret() {
  local docker_config_json
  if ! docker_config_json="$(resolve_docker_config_json)"; then
    printf 'Skipping pull secret creation because registry credentials are not set.\n' >&2
    return 0
  fi

  {
    cat <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ${PULL_SECRET_NAME}
  namespace: ${NAMESPACE}
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: |
EOF
    printf '%s\n' "${docker_config_json}" | sed 's/^/    /'
  } | "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" apply -f -
}

resolve_swr_password() {
  if [ -n "${SWR_PASSWORD_FILE:-}" ]; then
    cat "${SWR_PASSWORD_FILE}"
    return 0
  fi
  if [ -n "${SWR_PASSWORD:-}" ]; then
    printf '%s' "${SWR_PASSWORD}"
    return 0
  fi
  if [ -n "${SWR_DOCKER_CONFIG_JSON:-}" ]; then
    docker_config_field password
    return 0
  fi
  return 1
}

resolve_swr_username() {
  if [ -n "${SWR_USERNAME:-}" ]; then
    printf '%s' "${SWR_USERNAME}"
    return 0
  fi
  if [ -n "${SWR_DOCKER_CONFIG_JSON:-}" ]; then
    docker_config_field username
    return 0
  fi
  return 1
}

docker_config_field() {
  local field="$1"
  require_bin python3
  FIELD="${field}" REGISTRY_SERVER="${REGISTRY_SERVER}" python3 -c '
import base64
import json
import os
import sys

config = json.loads(os.environ["SWR_DOCKER_CONFIG_JSON"])
server = os.environ["REGISTRY_SERVER"]
field = os.environ["FIELD"]
entry = config.get("auths", {}).get(server)
if not entry:
    raise SystemExit(f"missing registry auth for {server}")
username = entry.get("username", "")
password = entry.get("password", "")
if (not username or not password) and entry.get("auth"):
    decoded = base64.b64decode(entry["auth"]).decode()
    username, _, password = decoded.partition(":")
value = username if field == "username" else password
if not value:
    raise SystemExit(f"missing {field} in docker config for {server}")
sys.stdout.write(value)
'
}

resolve_docker_config_json() {
  local password
  if [ -n "${SWR_DOCKER_CONFIG_JSON:-}" ]; then
    printf '%s' "${SWR_DOCKER_CONFIG_JSON}"
    return 0
  fi
  if [ -z "${SWR_USERNAME:-}" ]; then
    return 1
  fi
  if ! password="$(resolve_swr_password)"; then
    return 1
  fi

  require_bin python3
  printf '%s' "${password}" | REGISTRY_SERVER="${REGISTRY_SERVER}" SWR_USERNAME="${SWR_USERNAME}" python3 -c '
import base64
import json
import os
import sys

password = sys.stdin.read()
username = os.environ["SWR_USERNAME"]
server = os.environ["REGISTRY_SERVER"]
auth = base64.b64encode(f"{username}:{password}".encode()).decode()
print(json.dumps({"auths": {server: {"username": username, "password": password, "auth": auth}}}, separators=(",", ":")))
'
}

has_registry_credentials() {
  if [ -n "${SWR_DOCKER_CONFIG_JSON:-}" ]; then
    return 0
  fi
  if [ -z "${SWR_USERNAME:-}" ]; then
    return 1
  fi
  [ -n "${SWR_PASSWORD:-}" ] || [ -n "${SWR_PASSWORD_FILE:-}" ]
}

workload_resources() {
  local resources
  if ! resources="$("${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" get deploy,statefulset,daemonset -n "${NAMESPACE}" -o name)"; then
    printf 'Failed to list workloads in namespace %s.\n' "${NAMESPACE}" >&2
    exit 1
  fi
  if [ -z "${resources}" ]; then
    printf 'No workloads found in namespace %s.\n' "${NAMESPACE}" >&2
    exit 1
  fi
  printf '%s\n' "${resources}"
}

helm_deploy() {
  local -a helm_args=(
    upgrade --install "${RELEASE_NAME}" "${SCRIPT_DIR}/charts/yr-k8s"
    --kubeconfig "${KUBECONFIG_PATH}" \
    --namespace "${NAMESPACE}" \
    --create-namespace \
    -f "${VALUES_FILE}" \
    --set frontend.sandboxRouter.validateIam="${YR_K8S_VALIDATE_IAM:-true}" \
    --set global.namespace.create=false \
    --set global.namespace.name="${NAMESPACE}" \
    --set global.imageRegistry="${REGISTRY_REPO}" \
    --set global.images.controlplane.repository="yr-controlplane" \
    --set global.images.controlplane.tag="${IMAGE_TAG}" \
    --set global.images.node.repository="yr-node" \
    --set global.images.node.tag="${IMAGE_TAG}" \
    --set global.images.runtime.repository="yr-runtime" \
    --set global.images.runtime.tag="${RUNTIME_IMAGE_TAG_CP310}" \
    --set global.runtimeImages.cp39.tag="${RUNTIME_IMAGE_TAG_CP39}" \
    --set global.runtimeImages.cp310.tag="${RUNTIME_IMAGE_TAG_CP310}" \
    --set global.runtimeImages.cp311.tag="${RUNTIME_IMAGE_TAG_CP311}" \
    --set global.runtimeImages.cp312.tag="${RUNTIME_IMAGE_TAG_CP312}" \
    --set global.runtimeImages.cp313.tag="${RUNTIME_IMAGE_TAG_CP313}" \
    --set global.images.traefik.registry="${REGISTRY_REPO}" \
    --set global.images.traefik.repository="traefik" \
    --set global.images.traefik.tag="v2.11.14"
  )
  if [ -n "${EXTRA_VALUES_FILE}" ]; then
    if [ ! -f "${EXTRA_VALUES_FILE}" ]; then
      printf 'Missing extra values file: %s\n' "${EXTRA_VALUES_FILE}" >&2
      exit 1
    fi
    helm_args+=(-f "${EXTRA_VALUES_FILE}")
  fi
  "${HELM_BIN}" "${helm_args[@]}"
}

target_service_type() {
  local component="$1"
  python3 - "${component}" "${VALUES_FILE}" "${EXTRA_VALUES_FILE}" <<'PY'
import re
import sys

component = sys.argv[1]
target_type = ""
for path in [item for item in sys.argv[2:] if item]:
    section = []
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            key = line.strip().split(":", 1)[0].strip()
            value = line.strip().split(":", 1)[1].strip() if ":" in line else ""
            while section and section[-1][0] >= indent:
                section.pop()
            section.append((indent, key))
            if [item[1] for item in section] == [component, "service", "type"]:
                target_type = re.sub(r'^["\']|["\']$', "", value) or "ClusterIP"
print(target_type or "LoadBalancer")
PY
}

delete_legacy_load_balancer_service() {
  local component="$1"
  local display_name="$2"
  local target_type services service current_type
  target_type="$(target_service_type "${component}")"
  if [ "${target_type}" = "LoadBalancer" ]; then
    return 0
  fi

  services="$("${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" get svc \
    --namespace "${NAMESPACE}" \
    -l app.kubernetes.io/instance="${RELEASE_NAME}",app.kubernetes.io/component="${component}" \
    -o name 2>/dev/null || true)"
  while IFS= read -r service; do
    [ -n "${service}" ] || continue
    current_type="$("${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" get "${service}" \
      --namespace "${NAMESPACE}" \
      -o "jsonpath={.spec.type}")"
    if [ "${current_type}" != "LoadBalancer" ]; then
      continue
    fi
    printf 'Deleting legacy %s LoadBalancer service %s before recreating it as %s.\n' \
      "${display_name}" "${service}" "${target_type}" >&2
    "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" delete "${service}" \
      --namespace "${NAMESPACE}" \
      --wait=true
  done <<<"${services}"
}

delete_legacy_load_balancer_services() {
  delete_legacy_load_balancer_service traefik Traefik
  delete_legacy_load_balancer_service frontend Frontend
}

patch_workloads_with_pull_secret() {
  if ! has_registry_credentials; then
    printf 'Skipping workload imagePullSecrets patch because no registry credentials were provided.\n' >&2
    return 0
  fi

  local resource
  while IFS= read -r resource; do
    [ -n "${resource}" ] || continue
    "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" patch "${resource}" \
      --namespace "${NAMESPACE}" \
      --type merge \
      -p "{\"spec\":{\"template\":{\"spec\":{\"imagePullSecrets\":[{\"name\":\"${PULL_SECRET_NAME}\"}]}}}}"
  done < <(workload_resources)
}

wait_for_rollout() {
  local resource
  while IFS= read -r resource; do
    [ -n "${resource}" ] || continue
    "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" rollout status "${resource}" \
      --namespace "${NAMESPACE}" \
      --timeout="${YR_K8S_ROLLOUT_TIMEOUT:-20m}"
  done < <(workload_resources)
}

frontend_deployment() {
  "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" get deploy \
    --namespace "${NAMESPACE}" \
    -l app.kubernetes.io/instance="${RELEASE_NAME}",app.kubernetes.io/component=frontend \
    -o name
}

restart_frontend_after_master_ready() {
  local deployments deployment count
  deployments="$(frontend_deployment)"
  count="$(printf '%s\n' "${deployments}" | sed '/^$/d' | wc -l)"
  if [ "${count}" -ne 1 ]; then
    printf 'Expected exactly one frontend deployment for release %s in namespace %s, found %s.\n' \
      "${RELEASE_NAME}" "${NAMESPACE}" "${count}" >&2
    exit 1
  fi

  deployment="${deployments}"
  printf 'Restarting %s after master rollout to refresh the frontend driver.\n' "${deployment}" >&2
  "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" rollout restart "${deployment}" --namespace "${NAMESPACE}"
  "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" rollout status "${deployment}" \
    --namespace "${NAMESPACE}" \
    --timeout="${YR_K8S_ROLLOUT_TIMEOUT:-20m}"
}

node_pods() {
  "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" get pods \
    --namespace "${NAMESPACE}" \
    -l app.kubernetes.io/instance="${RELEASE_NAME}",app.kubernetes.io/component=node \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
}

prepull_runtime_image() {
  if ! has_registry_credentials; then
    printf 'Skipping runtime image pre-pull because no registry credentials were provided.\n' >&2
    return 0
  fi

  local pods pod username password runtime_image suffix tag
  local -a runtime_images=()
  for suffix in ${YR_K8S_PREPULL_RUNTIME_SUFFIXES:-cp39 cp310 cp311 cp312 cp313}; do
    case "${suffix}" in
    cp39) tag="${RUNTIME_IMAGE_TAG_CP39}" ;;
    cp310) tag="${RUNTIME_IMAGE_TAG_CP310}" ;;
    cp311) tag="${RUNTIME_IMAGE_TAG_CP311}" ;;
    cp312) tag="${RUNTIME_IMAGE_TAG_CP312}" ;;
    cp313) tag="${RUNTIME_IMAGE_TAG_CP313}" ;;
    *)
      printf 'Unknown runtime pre-pull suffix: %s\n' "${suffix}" >&2
      exit 1
      ;;
    esac
    runtime_images+=("${REGISTRY_REPO}/yr-runtime:${tag}")
  done
  pods="$(node_pods)"
  if [ -z "${pods}" ]; then
    printf 'No node pods found for release %s in namespace %s.\n' "${RELEASE_NAME}" "${NAMESPACE}" >&2
    exit 1
  fi

  username="$(resolve_swr_username)"
  password="$(resolve_swr_password)"
  while IFS= read -r pod; do
    [ -n "${pod}" ] || continue
    for runtime_image in "${runtime_images[@]}"; do
      printf 'Pre-pulling runtime image %s on %s.\n' "${runtime_image}" "${pod}" >&2
      printf '%s' "${password}" | "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" exec \
        --namespace "${NAMESPACE}" -i "${pod}" -c node -- sh -eu -c '
          docker login "$1" -u "$2" --password-stdin >/dev/null
          docker pull "$3"
        ' sh "${REGISTRY_SERVER}" "${username}" "${runtime_image}"
    done
  done <<<"${pods}"
}

show_status() {
  printf '\nNamespace: %s\n' "${NAMESPACE}" >&2
  "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" get pods,svc,statefulset,deploy,daemonset -n "${NAMESPACE}"
}

main() {
  require_bin "${KUBECTL_BIN}"
  require_bin "${HELM_BIN}"

  if [ ! -f "${KUBECONFIG_PATH}" ]; then
    printf 'Missing kubeconfig: %s\n' "${KUBECONFIG_PATH}" >&2
    exit 1
  fi

  validate_k8s_name "${NAMESPACE}" "YR_K8S_NAMESPACE"
  validate_k8s_name "${PULL_SECRET_NAME}" "YR_K8S_PULL_SECRET_NAME"
  create_namespace
  create_or_update_pull_secret
  delete_legacy_load_balancer_services
  helm_deploy
  patch_workloads_with_pull_secret
  wait_for_rollout
  restart_frontend_after_master_ready
  prepull_runtime_image
  show_status
}

main "$@"
