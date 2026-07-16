#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VARIANT="${PYTHON314_BUILDER_VARIANT:?Set PYTHON314_BUILDER_VARIANT to compile or rust}"
ARCH="${PYTHON314_BUILDER_ARCH:?Set PYTHON314_BUILDER_ARCH to amd64 or arm64}"
BASE_IMAGE="${PYTHON314_BUILDER_BASE_IMAGE:?Set PYTHON314_BUILDER_BASE_IMAGE to an existing bootstrap image}"
OUTPUT_TAG="${PYTHON314_BUILDER_OUTPUT_TAG:?Set PYTHON314_BUILDER_OUTPUT_TAG to an architecture staging tag}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
DOCKERD_PID=""
. "${ROOT_DIR}/.buildkite/docker_job_helpers.sh"

case "${VARIANT}" in
compile|rust) ;;
*) printf 'Unsupported builder variant: %s\n' "${VARIANT}" >&2; exit 1 ;;
esac
case "${ARCH}" in
amd64|arm64) ;;
*) printf 'Unsupported builder architecture: %s\n' "${ARCH}" >&2; exit 1 ;;
esac
if [ "${VARIANT}" = rust ] && [ "${ARCH}" != amd64 ]; then
    printf 'The Rust Python 3.14 builder is supported only on amd64.\n' >&2
    exit 1
fi
if [ "${VARIANT}" = compile ]; then
    case "${OUTPUT_TAG}" in
    *-"${ARCH}") ;;
    *) printf 'Output tag must end in -%s: %s\n' "${ARCH}" "${OUTPUT_TAG}" >&2; exit 1 ;;
    esac
fi
if ! command -v "${DOCKER_BIN}" >/dev/null 2>&1; then
    printf 'Missing required container CLI: %s\n' "${DOCKER_BIN}" >&2
    exit 1
fi

trap docker_job_stop_dockerd EXIT

docker_login() {
    local registry="${OUTPUT_TAG%%/*}"
    if [ -n "${SWR_USERNAME:-}" ] && [ -n "${SWR_PASSWORD:-}" ]; then
        printf '%s' "${SWR_PASSWORD}" | "${DOCKER_BIN}" login "${registry}" -u "${SWR_USERNAME}" --password-stdin
        return 0
    fi
    if [ -n "${SWR_DOCKER_CONFIG_JSON:-}" ]; then
        mkdir -p "${HOME}/.docker"
        printf '%s' "${SWR_DOCKER_CONFIG_JSON}" >"${HOME}/.docker/config.json"
        return 0
    fi
    printf 'SWR credentials are required to publish %s.\n' "${OUTPUT_TAG}" >&2
    exit 1
}

docker_job_start_dockerd "${ROOT_DIR}/artifacts/python314-builder/dockerd.log"
docker_login
daemon_arch="$(${DOCKER_BIN} info --format '{{.Architecture}}')"
case "${ARCH}:${daemon_arch}" in
amd64:amd64|amd64:x86_64|arm64:arm64|arm64:aarch64) ;;
*) printf 'Native Docker architecture mismatch: requested %s, daemon is %s\n' "${ARCH}" "${daemon_arch}" >&2; exit 1 ;;
esac

"${DOCKER_BIN}" build \
    --platform "linux/${ARCH}" \
    --build-arg BASE_IMAGE="${BASE_IMAGE}" \
    --build-arg PYTHON_VERSION=3.14.6 \
    --tag "${OUTPUT_TAG}" \
    --file "${ROOT_DIR}/ci/ubuntu/Dockerfile.python314-overlay" \
    "${ROOT_DIR}"
"${DOCKER_BIN}" push "${OUTPUT_TAG}"
"${DOCKER_BIN}" run --rm --platform "linux/${ARCH}" --entrypoint python3.14 "${OUTPUT_TAG}" \
    -c 'import platform; assert platform.python_version() == "3.14.6"'
if [ "${VARIANT}" = rust ]; then
    "${DOCKER_BIN}" run --rm --platform linux/amd64 --entrypoint sh "${OUTPUT_TAG}" \
        -eu -c 'rustc --version; cargo --version'
fi
