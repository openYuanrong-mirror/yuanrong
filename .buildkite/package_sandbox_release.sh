#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

BUILD_STEP_KEY="${SANDBOX_BUILD_STEP_KEY:-build-all-amd64}"
OUTPUT_DIR="${ROOT_DIR}/output"
RELEASE_ARTIFACT_DIR="${ROOT_DIR}/artifacts/release"
SANDBOX_ARTIFACT_DIR="${ROOT_DIR}/artifacts/sandbox"
HELM_DIR="${SANDBOX_ARTIFACT_DIR}/helm"
MANIFEST_DIR="${SANDBOX_ARTIFACT_DIR}/manifests"
METADATA_DIR="${SANDBOX_ARTIFACT_DIR}/metadata"
CHART_DIR="${ROOT_DIR}/deploy/sandbox/k8s/charts/yr-k8s"
VALUES_FILE="${ROOT_DIR}/deploy/sandbox/k8s/k8s/values.prod.yaml"
REGISTRY_REPO="${YR_K8S_REGISTRY_REPO:-swr.cn-southwest-2.myhuaweicloud.com/openyuanrong}"
REGISTRY_SERVER="${YR_K8S_REGISTRY_SERVER:-swr.cn-southwest-2.myhuaweicloud.com}"
TRAEFIK_IMAGE_REGISTRY="${YR_K8S_TRAEFIK_IMAGE_REGISTRY:-${REGISTRY_REPO}}"
TRAEFIK_IMAGE_TAG="${YR_K8S_TRAEFIK_IMAGE_TAG:-v2.11.14}"
COMMIT_SHA="${BUILDKITE_COMMIT:-$(git rev-parse HEAD)}"
SHORT_SHA="${COMMIT_SHA:0:12}"
BUILD_NUMBER="${BUILDKITE_BUILD_NUMBER:-0}"
BRANCH_NAME="${BUILDKITE_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
SANITIZED_BRANCH="$(printf '%s' "${BRANCH_NAME}" | tr '/:_@' '----' | tr -cd '[:alnum:].-' | cut -c1-64)"
[ -n "${SANITIZED_BRANCH}" ] || SANITIZED_BRANCH="build"
IMAGE_TAG="${YR_K8S_IMAGE_TAG:-${SANITIZED_BRANCH}-${BUILD_NUMBER}-${SHORT_SHA}}"
CHART_VERSION="${YR_K8S_CHART_VERSION:-0.1.0+buildkite.${BUILD_NUMBER}.${SHORT_SHA}}"
APP_VERSION="${YR_K8S_APP_VERSION:-${SHORT_SHA}}"
DOCKERD_PID=""

require_bin() {
    local bin_name="$1"
    if ! command -v "${bin_name}" >/dev/null 2>&1; then
        printf 'Missing required CLI: %s\n' "${bin_name}" >&2
        exit 1
    fi
}

cleanup() {
    if [ -n "${DOCKERD_PID}" ]; then
        kill "${DOCKERD_PID}" >/dev/null 2>&1 || true
        wait "${DOCKERD_PID}" >/dev/null 2>&1 || true
    fi
}

trap cleanup EXIT

wait_for_docker() {
    local timeout="${DOCKER_READY_TIMEOUT:-60}"
    local i
    for i in $(seq 1 "${timeout}"); do
        if docker info >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

start_dockerd() {
    local driver="${DOCKER_DRIVER:-overlay2}"
    local log_file="${SANDBOX_ARTIFACT_DIR}/dockerd.log"

    if docker info >/dev/null 2>&1; then
        return 0
    fi
    if ! command -v dockerd >/dev/null 2>&1; then
        printf 'Docker daemon is unavailable and dockerd is not installed.\n' >&2
        exit 1
    fi

    mkdir -p "${SANDBOX_ARTIFACT_DIR}"
    : >"${log_file}"
    dockerd --host="${DOCKER_HOST:-unix:///var/run/docker.sock}" --storage-driver="${driver}" >>"${log_file}" 2>&1 &
    DOCKERD_PID="$!"
    if wait_for_docker; then
        return 0
    fi

    kill "${DOCKERD_PID}" >/dev/null 2>&1 || true
    wait "${DOCKERD_PID}" >/dev/null 2>&1 || true
    DOCKERD_PID=""

    printf 'dockerd with %s did not become ready, retrying with vfs.\n' "${driver}" >&2
    : >"${log_file}"
    dockerd --host="${DOCKER_HOST:-unix:///var/run/docker.sock}" --storage-driver=vfs >>"${log_file}" 2>&1 &
    DOCKERD_PID="$!"
    if wait_for_docker; then
        return 0
    fi

    printf 'dockerd failed to start. Log follows:\n' >&2
    cat "${log_file}" >&2
    exit 1
}

download_release_artifacts() {
    mkdir -p "${OUTPUT_DIR}" "${RELEASE_ARTIFACT_DIR}"

    if command -v buildkite-agent >/dev/null 2>&1; then
        rm -rf "${OUTPUT_DIR}" "${RELEASE_ARTIFACT_DIR}"
        mkdir -p "${OUTPUT_DIR}" "${RELEASE_ARTIFACT_DIR}"
        buildkite-agent artifact download "artifacts/release/openyuanrong-*.whl" . --step "${BUILD_STEP_KEY}"
        buildkite-agent artifact download "artifacts/release/openyuanrong_sdk*.whl" . --step "${BUILD_STEP_KEY}"
    elif compgen -G "${OUTPUT_DIR}/openyuanrong-*.whl" >/dev/null \
        && compgen -G "${OUTPUT_DIR}/openyuanrong_sdk*.whl" >/dev/null; then
        return 0
    fi

    if compgen -G "${RELEASE_ARTIFACT_DIR}/*" >/dev/null; then
        cp -af "${RELEASE_ARTIFACT_DIR}/." "${OUTPUT_DIR}/"
    fi
}

docker_login_if_configured() {
    if [ -z "${SWR_USERNAME:-}" ] || [ -z "${SWR_PASSWORD:-}" ]; then
        if [ -n "${SWR_DOCKER_CONFIG_JSON:-}" ]; then
            mkdir -p "${HOME}/.docker"
            printf '%s' "${SWR_DOCKER_CONFIG_JSON}" >"${HOME}/.docker/config.json"
            printf 'Using Docker registry config from swr-pull-secret.\n' >&2
            return 0
        fi
        if [[ "${REGISTRY_SERVER}" == swr.*.myhuaweicloud.com ]]; then
            printf 'SWR_USERNAME/SWR_PASSWORD are required to push to %s.\n' "${REGISTRY_SERVER}" >&2
            printf 'Create swr-credentials, provide swr-pull-secret, or pass these environment variables in Buildkite.\n' >&2
            exit 1
        fi
        printf 'SWR_USERNAME/SWR_PASSWORD not set; assuming docker is already authenticated.\n' >&2
        return 0
    fi

    printf '%s' "${SWR_PASSWORD}" | docker login "${REGISTRY_SERVER}" -u "${SWR_USERNAME}" --password-stdin
}

write_values_override() {
    cat >"${METADATA_DIR}/yr-k8s-image-values.yaml" <<EOF
global:
  imageRegistry: ${REGISTRY_REPO}
  images:
    controlplane:
      repository: yr-controlplane
      tag: ${IMAGE_TAG}
    node:
      repository: yr-node
      tag: ${IMAGE_TAG}
    runtime:
      repository: yr-runtime
      tag: ${IMAGE_TAG}
    traefik:
      registry: ${TRAEFIK_IMAGE_REGISTRY}
      repository: traefik
      tag: ${TRAEFIK_IMAGE_TAG}
EOF
}

write_metadata() {
    cat >"${METADATA_DIR}/sandbox-release.json" <<EOF
{
  "commit": "${COMMIT_SHA}",
  "branch": "${BRANCH_NAME}",
  "build_number": "${BUILD_NUMBER}",
  "registry": "${REGISTRY_REPO}",
  "image_tag": "${IMAGE_TAG}",
  "chart_version": "${CHART_VERSION}",
  "app_version": "${APP_VERSION}",
  "images": [
    "${REGISTRY_REPO}/yr-controlplane:${IMAGE_TAG}",
    "${REGISTRY_REPO}/yr-node:${IMAGE_TAG}",
    "${REGISTRY_REPO}/yr-runtime:${IMAGE_TAG}"
  ],
  "static_images": [
    "${TRAEFIK_IMAGE_REGISTRY}/traefik:${TRAEFIK_IMAGE_TAG}"
  ]
}
EOF
}

upload_helm_to_obs_if_configured() {
    if [ -z "${OBS_ACCESS_KEY_ID:-}" ] || [ -z "${OBS_SECRET_ACCESS_KEY:-}" ]; then
        printf 'OBS credentials not set; skipping Helm package upload to OBS.\n' >&2
        return 0
    fi

    python3 -c "from obs import ObsClient"
    local chart_pkg
    chart_pkg="$(find "${HELM_DIR}" -maxdepth 1 -type f -name 'yr-k8s-*.tgz' | sort | tail -1)"
    python3 tools/upload_build_artifact.py \
        --file "${chart_pkg}" \
        --kind build \
        --channel daily \
        --platform helm \
        --arch noarch \
        --timestamp "$(date '+%Y%m%d%H%M%S')"
}

main() {
    mkdir -p "${HELM_DIR}" "${MANIFEST_DIR}" "${METADATA_DIR}"

    require_bin docker
    require_bin helm
    require_bin python3

    download_release_artifacts
    start_dockerd
    docker_login_if_configured

    export YR_K8S_IMAGE_TAG="${IMAGE_TAG}"
    export YR_K8S_REGISTRY_REPO="${REGISTRY_REPO}"
    bash deploy/sandbox/k8s/build-images.sh
    bash deploy/sandbox/k8s/push-images-swr.sh

    write_values_override
    write_metadata

    helm lint "${CHART_DIR}" -f "${VALUES_FILE}" -f "${METADATA_DIR}/yr-k8s-image-values.yaml"
    helm template yr-k8s "${CHART_DIR}" \
        -f "${VALUES_FILE}" \
        -f "${METADATA_DIR}/yr-k8s-image-values.yaml" \
        >"${MANIFEST_DIR}/yr-k8s.yaml"
    helm package "${CHART_DIR}" \
        --version "${CHART_VERSION}" \
        --app-version "${APP_VERSION}" \
        --destination "${HELM_DIR}"

    upload_helm_to_obs_if_configured

    if command -v buildkite-agent >/dev/null 2>&1; then
        buildkite-agent artifact upload "${SANDBOX_ARTIFACT_DIR}/**/*" || true
        buildkite-agent annotate --style "success" --context "sandbox-release" \
            "Sandbox images pushed with tag ${IMAGE_TAG}; Helm chart packaged as version ${CHART_VERSION}."
    fi
}

main "$@"
