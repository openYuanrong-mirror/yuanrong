#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

BUILD_STEP_KEY="${CI_PIPELINE_BUILD_STEP_KEY:-build-all-amd64}"
CI_PIPELINE_REPO="${CI_PIPELINE_REPO:-https://gitcode.com/OpenYuangRong_CI/ci-pipeline.git}"
CI_PIPELINE_REF="${CI_PIPELINE_REF:-main}"
CI_PIPELINE_DIR="${ROOT_DIR}/artifacts/ci-pipeline"
OBS_URL_DIR="${ROOT_DIR}/artifacts/ci-pipeline-obs-urls"
LOG_DIR="${ROOT_DIR}/artifacts/ci-pipeline-image-logs"
REGISTRY_SERVER="${CI_PIPELINE_REGISTRY_SERVER:-swr.cn-southwest-2.myhuaweicloud.com}"
DOCKERD_PID=""

cleanup() {
    if [ -n "${DOCKERD_PID}" ]; then
        kill "${DOCKERD_PID}" >/dev/null 2>&1 || true
        wait "${DOCKERD_PID}" >/dev/null 2>&1 || true
    fi
}

trap cleanup EXIT

require_bin() {
    local bin_name="$1"
    if ! command -v "${bin_name}" >/dev/null 2>&1; then
        printf 'Missing required CLI: %s\n' "${bin_name}" >&2
        exit 1
    fi
}

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
    local log_file="${LOG_DIR}/dockerd.log"

    if docker info >/dev/null 2>&1; then
        return 0
    fi
    if ! command -v dockerd >/dev/null 2>&1; then
        printf 'Docker daemon is unavailable and dockerd is not installed.\n' >&2
        exit 1
    fi

    mkdir -p "${LOG_DIR}"
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

docker_login_if_configured() {
    if [ -z "${SWR_USERNAME:-}" ] || [ -z "${SWR_PASSWORD:-}" ]; then
        if [ -n "${SWR_DOCKER_CONFIG_JSON:-}" ]; then
            mkdir -p "${HOME}/.docker"
            printf '%s' "${SWR_DOCKER_CONFIG_JSON}" >"${HOME}/.docker/config.json"
            printf 'Using Docker registry config from swr-pull-secret.\n' >&2
            return 0
        fi
        printf 'SWR credentials are not set; assuming docker is already authenticated.\n' >&2
        return 0
    fi

    printf '%s' "${SWR_PASSWORD}" | docker login "${REGISTRY_SERVER}" -u "${SWR_USERNAME}" --password-stdin
}

default_docker_buildkit() {
    case "$(uname -m)" in
        aarch64) printf '0' ;;
        *) printf '1' ;;
    esac
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

    awk -F '\t' '$1 ~ /^openyuanrong-.*[.]tar[.]gz$/ {print $2}' \
        "${OBS_URL_DIR}/${BUILD_STEP_KEY}/obs-urls.txt" | sort | tail -1
}

clone_ci_pipeline() {
    rm -rf "${CI_PIPELINE_DIR}"
    git clone --depth=1 --branch "${CI_PIPELINE_REF}" "${CI_PIPELINE_REPO}" "${CI_PIPELINE_DIR}"
}

main() {
    require_bin docker
    require_bin git
    require_bin awk

    local tar_url
    tar_url="$(resolve_openyuanrong_tar_url)"
    if [ -z "${tar_url}" ]; then
        printf 'No openyuanrong tar URL found in obs-urls.%s metadata.\n' "${BUILD_STEP_KEY}" >&2
        exit 1
    fi
    printf 'Using openyuanrong tar for ci-pipeline image build: %s\n' "${tar_url}"

    clone_ci_pipeline
    if [ "${CI_PIPELINE_DRY_RUN:-0}" = "1" ]; then
        printf 'CI_PIPELINE_DRY_RUN=1; skip docker build and push.\n'
        return 0
    fi

    start_dockerd
    docker_login_if_configured

    export DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-$(default_docker_buildkit)}"
    cd "${CI_PIPELINE_DIR}/build/k8s"
    bash -x build.sh \
        -v "${CI_PIPELINE_BUILD_VERSION:-9.9.9}" \
        -p "${tar_url}" \
        -t docker \
        -s "${CI_PIPELINE_IMAGE_TIMESTAMP:-${BUILDKITE_BUILD_NUMBER:-local}}"
}

main "$@"
