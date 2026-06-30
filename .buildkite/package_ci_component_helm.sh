#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

BUILD_STEP_KEY="${CI_PIPELINE_BUILD_STEP_KEY:-build-all-amd64}"
CI_PIPELINE_REPO="${CI_PIPELINE_REPO:-https://gitcode.com/OpenYuangRong_CI/ci-pipeline.git}"
CI_PIPELINE_REF="${CI_PIPELINE_REF:-main}"
CI_PIPELINE_DIR="${ROOT_DIR}/artifacts/ci-pipeline-component-helm"
WORK_DIR="${ROOT_DIR}/artifacts/ci-pipeline-component-helm-work"
OBS_URL_DIR="${ROOT_DIR}/artifacts/ci-pipeline-obs-urls"
PACKAGE_DIR="${COMPONENT_HELM_PACKAGE_DIR:-${ROOT_DIR}/artifacts/sandbox/helm}"
MANIFEST_DIR="${COMPONENT_HELM_MANIFEST_DIR:-${ROOT_DIR}/artifacts/sandbox/manifests}"
METADATA_DIR="${COMPONENT_HELM_METADATA_DIR:-${ROOT_DIR}/artifacts/sandbox/metadata}"
IMAGE_REPO="${SANDBOX_COMPONENT_IMAGE_REGISTRY_REPO:-${CI_PIPELINE_REGISTRY_REPO:-swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev}}"
IMAGE_TAG="${SANDBOX_COMPONENT_IMAGE_TAG:-daily.${CI_PIPELINE_IMAGE_TIMESTAMP:-${BUILDKITE_BUILD_NUMBER:-local}}}"
CHART_PATCH="${CI_PIPELINE_CHART_VERSION_PATCH:-${CI_PIPELINE_IMAGE_TIMESTAMP:-${BUILDKITE_BUILD_NUMBER:-0}}}"
case "${CHART_PATCH}" in
    ""|*[!0-9]*) CHART_PATCH="0" ;;
esac
CHART_VERSION="${CI_PIPELINE_CHART_VERSION:-1.0.${CHART_PATCH}}"

require_bin() {
    local bin_name="$1"
    if ! command -v "${bin_name}" >/dev/null 2>&1; then
        printf 'Missing required CLI: %s\n' "${bin_name}" >&2
        exit 1
    fi
}

resolve_openyuanrong_tar_url() {
    mkdir -p "${OBS_URL_DIR}/${BUILD_STEP_KEY}"
    if command -v buildkite-agent >/dev/null 2>&1; then
        buildkite-agent meta-data get "obs-urls.${BUILD_STEP_KEY}" \
            >"${OBS_URL_DIR}/${BUILD_STEP_KEY}/obs-urls.txt"
    elif [ -n "${CI_PIPELINE_OPENYUANRONG_TAR_URL:-}" ]; then
        printf 'openyuanrong.tar.gz\t%s\n' "${CI_PIPELINE_OPENYUANRONG_TAR_URL}" \
            >"${OBS_URL_DIR}/${BUILD_STEP_KEY}/obs-urls.txt"
    else
        printf 'CI_PIPELINE_OPENYUANRONG_TAR_URL is required outside Buildkite.\n' >&2
        exit 1
    fi

    awk -F '\t' '$1 ~ /^openyuanrong(-.*)?[.]tar[.]gz$/ {print $2}' \
        "${OBS_URL_DIR}/${BUILD_STEP_KEY}/obs-urls.txt" | sort | tail -1
}

fetch_openyuanrong_tar() {
    local tar_ref="$1"
    local tar_file="${WORK_DIR}/openyuanrong.tar.gz"
    case "${tar_ref}" in
        http://*|https://*)
            curl -L --fail --silent --show-error "${tar_ref}" -o "${tar_file}"
            ;;
        file://*)
            cp "${tar_ref#file://}" "${tar_file}"
            ;;
        *)
            cp "${tar_ref}" "${tar_file}"
            ;;
    esac
    printf '%s\n' "${tar_file}"
}

clone_ci_pipeline() {
    rm -rf "${CI_PIPELINE_DIR}"
    git clone --depth=1 --branch "${CI_PIPELINE_REF}" "${CI_PIPELINE_REPO}" "${CI_PIPELINE_DIR}"
}

replace_in_file() {
    local file="$1"
    local pattern="$2"
    local replacement="$3"
    sed -i.bak "s@${pattern}@${replacement}@g" "${file}"
    rm -f "${file}.bak"
}

main() {
    require_bin curl
    require_bin git
    require_bin helm
    require_bin tar

    local tar_url
    tar_url="$(resolve_openyuanrong_tar_url)"
    if [ -z "${tar_url}" ]; then
        printf 'No openyuanrong tar URL found in obs-urls.%s metadata.\n' "${BUILD_STEP_KEY}" >&2
        exit 1
    fi

    rm -rf "${WORK_DIR}"
    mkdir -p \
        "${WORK_DIR}/extract" \
        "${WORK_DIR}/helm/OpenYuanRong/charts" \
        "${PACKAGE_DIR}" \
        "${MANIFEST_DIR}" \
        "${METADATA_DIR}"

    clone_ci_pipeline

    local tar_file
    tar_file="$(fetch_openyuanrong_tar "${tar_url}")"
    tar -xzf "${tar_file}" -C "${WORK_DIR}/extract" \
        openyuanrong/deploy/k8s/charts/openyuanrong \
        openyuanrong/deploy/k8s/charts/datasystem

    cp -R "${WORK_DIR}/extract/openyuanrong/deploy/k8s/charts/openyuanrong/." \
        "${WORK_DIR}/helm/OpenYuanRong/"
    cp -R "${WORK_DIR}/extract/openyuanrong/deploy/k8s/charts/datasystem" \
        "${WORK_DIR}/helm/OpenYuanRong/charts/"
    cp -R "${CI_PIPELINE_DIR}/build/k8s/base_charts/etcd" \
        "${WORK_DIR}/helm/OpenYuanRong/charts/"
    cp -R "${CI_PIPELINE_DIR}/build/k8s/base_charts/minio" \
        "${WORK_DIR}/helm/OpenYuanRong/charts/"

    replace_in_file "${WORK_DIR}/helm/OpenYuanRong/values.yaml" "ImageRepo" "${IMAGE_REPO}/"
    replace_in_file "${WORK_DIR}/helm/OpenYuanRong/values.yaml" "version_replace" "${IMAGE_TAG}"
    replace_in_file "${WORK_DIR}/helm/OpenYuanRong/charts/datasystem/values.yaml" "version_replace" "${IMAGE_TAG}"

    cp "${WORK_DIR}/helm/OpenYuanRong/values.yaml" "${METADATA_DIR}/openyuanrong-image-values.yaml"
    helm template openyuanrong "${WORK_DIR}/helm/OpenYuanRong" \
        >"${MANIFEST_DIR}/openyuanrong.yaml"
    helm package "${WORK_DIR}/helm/OpenYuanRong" \
        --version "${CHART_VERSION}" \
        --destination "${PACKAGE_DIR}"
}

main "$@"
