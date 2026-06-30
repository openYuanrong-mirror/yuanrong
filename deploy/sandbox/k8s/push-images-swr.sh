#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

REGISTRY_REPO="${YR_K8S_REGISTRY_REPO:-swr.cn-southwest-2.myhuaweicloud.com/openyuanrong}"
IMAGE_TAG="${YR_K8S_IMAGE_TAG:-$(date +%Y%m%d-%H%M%S)-$(git -C "${REPO_ROOT}" rev-parse --short HEAD)}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
IMAGE_PLATFORM="${YR_K8S_IMAGE_PLATFORM:-}"
CACHE_REGISTRY_REPO="${YR_K8S_CACHE_REGISTRY_REPO:-${REGISTRY_REPO}}"
IMAGE_CACHE_ENABLED="${YR_K8S_IMAGE_CACHE:-0}"
CACHE_TAG="${YR_K8S_IMAGE_CACHE_TAG:-build-cache}"
RUNTIME_ONLY="${YR_K8S_RUNTIME_ONLY:-0}"
local_images=(yr-base yr-compile yr-runtime yr-controlplane yr-node)
push_supports_platform=""

case "${RUNTIME_ONLY}" in
  1|true|TRUE|yes|YES|on|ON) local_images=(yr-runtime) ;;
esac

declare -A LOCAL_TO_REMOTE=(
  ["yr-base"]="${REGISTRY_REPO}/yr-base:${IMAGE_TAG}"
  ["yr-compile"]="${REGISTRY_REPO}/yr-compile:${IMAGE_TAG}"
  ["yr-runtime"]="${REGISTRY_REPO}/yr-runtime:${IMAGE_TAG}"
  ["yr-controlplane"]="${REGISTRY_REPO}/yr-controlplane:${IMAGE_TAG}"
  ["yr-node"]="${REGISTRY_REPO}/yr-node:${IMAGE_TAG}"
)

require_local_image() {
  local image_name="$1"
  if ! "${DOCKER_BIN}" image inspect "${image_name}:latest" >/dev/null 2>&1; then
    printf 'Missing local image: %s:latest\n' "${image_name}" >&2
    printf 'Build it first with: bash deploy/sandbox/k8s/build-images.sh\n' >&2
    exit 1
  fi
}

docker_push_supports_platform() {
  if [ -z "${push_supports_platform}" ]; then
    if "${DOCKER_BIN}" push --help 2>&1 | grep -q -- '--platform'; then
      push_supports_platform=1
    else
      push_supports_platform=0
    fi
  fi
  [ "${push_supports_platform}" = "1" ]
}

push_remote_image() {
  local remote_image="$1"

  if [ -n "${IMAGE_PLATFORM}" ] && docker_push_supports_platform; then
    "${DOCKER_BIN}" push --platform "${IMAGE_PLATFORM}" "${remote_image}"
  else
    if [ -n "${IMAGE_PLATFORM}" ] && ! docker_push_supports_platform; then
      printf 'Docker push does not support --platform; pushing local image for %s without platform flag.\n' \
        "${IMAGE_PLATFORM}" >&2
    fi
    "${DOCKER_BIN}" push "${remote_image}"
  fi
}

push_image() {
  local local_image="$1"
  local remote_image="$2"

  printf 'Tagging %s:latest -> %s\n' "${local_image}" "${remote_image}" >&2
  "${DOCKER_BIN}" tag "${local_image}:latest" "${remote_image}"

  printf 'Pushing %s\n' "${remote_image}" >&2
  push_remote_image "${remote_image}"

  if [ "${IMAGE_CACHE_ENABLED}" = "1" ]; then
    local cache_image="${CACHE_REGISTRY_REPO}/${local_image}:${CACHE_TAG}"
    printf 'Updating image cache %s:latest -> %s\n' "${local_image}" "${cache_image}" >&2
    "${DOCKER_BIN}" tag "${local_image}:latest" "${cache_image}"
    push_remote_image "${cache_image}"
  fi
}

main() {
  if ! command -v "${DOCKER_BIN}" >/dev/null 2>&1; then
    printf 'Missing container CLI: %s\n' "${DOCKER_BIN}" >&2
    exit 1
  fi

  printf 'Using target repository: %s\n' "${REGISTRY_REPO}" >&2
  printf 'Using image tag: %s\n' "${IMAGE_TAG}" >&2

  for local_image in "${local_images[@]}"; do
    require_local_image "${local_image}"
  done

  for local_image in "${local_images[@]}"; do
    push_image "${local_image}" "${LOCAL_TO_REMOTE[${local_image}]}"
  done

  printf '\nPushed images:\n' >&2
  for local_image in "${local_images[@]}"; do
    printf '  %s\n' "${LOCAL_TO_REMOTE[${local_image}]}" >&2
  done
  printf '\nTraefik is a fixed third-party image. Preload it once as: %s/traefik:v2.11.14\n' "${REGISTRY_REPO}" >&2

  printf '\nSuggested deploy command:\n' >&2
  cat >&2 <<EOF
  helm upgrade --install yr-k8s deploy/sandbox/k8s/charts/yr-k8s \\
    -n yr --create-namespace \\
    -f deploy/sandbox/k8s/k8s/values.local.yaml \\
    --set global.imageRegistry=${REGISTRY_REPO} \\
    --set global.images.controlplane.repository=yr-controlplane \\
    --set global.images.controlplane.tag=${IMAGE_TAG} \\
    --set global.images.node.repository=yr-node \\
    --set global.images.node.tag=${IMAGE_TAG} \\
    --set global.images.runtime.repository=yr-runtime \\
    --set global.images.runtime.tag=${IMAGE_TAG} \\
    --set global.images.traefik.registry=${REGISTRY_REPO} \\
    --set global.images.traefik.repository=traefik \\
    --set global.images.traefik.tag=v2.11.14
EOF
}

main "$@"
