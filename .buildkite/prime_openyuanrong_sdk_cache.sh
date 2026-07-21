#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_ARCH="${1:-}"
case "${BUILD_ARCH}" in
    amd64|arm64) ;;
    *)
        printf 'Usage: %s <amd64|arm64>\n' "$0" >&2
        exit 2
        ;;
esac

export PATH="/opt/buildtools/python3.9/bin:/usr/local/bin:/usr/bin:${PATH}"
export CC="${CC:-gcc-10}"
export CXX="${CXX:-g++-10}"
export PIP_BREAK_SYSTEM_PACKAGES=1

COMMIT_FOR_VERSION="${BUILDKITE_COMMIT:-$(git -C "${ROOT_DIR}" rev-parse HEAD)}"
SHORT_COMMIT="$(printf '%s' "${COMMIT_FOR_VERSION}" | cut -c1-12)"
TAG_BUILD_VERSION="${YR_RELEASE_TAG:-${BUILDKITE_TAG:-}}"
TAG_BUILD_VERSION="${TAG_BUILD_VERSION#refs/tags/}"
case "${TAG_BUILD_VERSION}" in v[0-9]*) TAG_BUILD_VERSION="${TAG_BUILD_VERSION#v}" ;; esac
YR_BUILD_VERSION="${YR_BUILD_VERSION:-${BUILD_VERSION:-${TAG_BUILD_VERSION:-0.7.0+${SHORT_COMMIT}}}}"
BAZEL_BUILD_VERSION="${BAZEL_BUILD_VERSION:-${TAG_BUILD_VERSION:-$(cat "${ROOT_DIR}/VERSION")}}"
export BUILD_VERSION="${YR_BUILD_VERSION}"
export BAZEL_BUILD_VERSION
export COMMIT_ID="${COMMIT_FOR_VERSION}"

CACHE_BASE="${YR_BUILDKITE_CACHE_BASE:-/mnt/paas/build-cache}"
mkdir -p \
    "${CACHE_BASE}/go-mod" \
    "${CACHE_BASE}/go-cache/${BUILD_ARCH}" \
    "${CACHE_BASE}/pip" \
    "${CACHE_BASE}/bazel-repository-cache/${BUILD_ARCH}"
export GOMODCACHE="${CACHE_BASE}/go-mod"
export GOCACHE="${CACHE_BASE}/go-cache/${BUILD_ARCH}"
export PIP_CACHE_DIR="${CACHE_BASE}/pip"
export BAZEL_REPOSITORY_CACHE="${CACHE_BASE}/bazel-repository-cache/${BUILD_ARCH}"

cd "${ROOT_DIR}"
bash .buildkite/prepare_sdk_thirdparty_cache.sh "${CACHE_BASE}"
export SKIP_RUNTIME_DEPENDENCY_DOWNLOAD=1
. .buildkite/configure_bazel_remote_cache.sh

if [ -z "${REMOTE_CACHE:-}" ]; then
    echo "Skipping SDK native cache prime because remote cache is unavailable"
    exit 0
fi

git submodule sync --recursive
git submodule update --init --recursive --force --jobs=4
SDK_BUILD_MODE=common \
SDK_COMMON_PYTHON_VERSION=python3.9 \
SDK_PYTHON_VERSIONS=python3.9 \
    bash .buildkite/build_openyuanrong_sdk_wheels.sh output
