#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE_BASE="${1:-/mnt/paas/build-cache}"
BUILD_ARCH="${BUILD_ARCH:-$(uname -m)}"

case "${BUILD_ARCH}" in
    amd64|x86_64) CACHE_ARCH="amd64" ;;
    arm64|aarch64) CACHE_ARCH="arm64" ;;
    *) CACHE_ARCH="${BUILD_ARCH}" ;;
esac

THIRD_PARTY_CACHE_DIR="${CACHE_BASE}/thirdparty/sdk-${CACHE_ARCH}"
THIRD_PARTY_LOCK="${CACHE_BASE}/thirdparty/sdk-${CACHE_ARCH}.lock"
READY_MARKER="${THIRD_PARTY_CACHE_DIR}/.sdk-cache-ready"

download_sdk_thirdparty_sources() {
    local dependency_list

    dependency_list="$(mktemp)"
    trap 'rm -f "${dependency_list}"' RETURN
    awk -F, '$1 == "boost" || $1 == "libboundscheck" {print}' \
        "${ROOT_DIR}/tools/openSource.txt" >"${dependency_list}"
    bash "${ROOT_DIR}/tools/download_opensource.sh" \
        -M runtime \
        -F "${dependency_list}" \
        -T "${THIRD_PARTY_CACHE_DIR}"
}

compile_boost_libs() {
    if [ -d "${THIRD_PARTY_CACHE_DIR}/boost/lib" ]; then
        return 0
    fi

    pushd "${THIRD_PARTY_CACHE_DIR}/boost" >/dev/null
    chmod -R 700 "${THIRD_PARTY_CACHE_DIR}/boost"
    ./bootstrap.sh --without-libraries=python
    ./b2 cxxflags=-fPIC cflags=-fPIC link=static install --with-fiber --with-atomic \
        --prefix="${THIRD_PARTY_CACHE_DIR}/boost"
    popd >/dev/null
}

mkdir -p "$(dirname "${THIRD_PARTY_CACHE_DIR}")" "${THIRD_PARTY_CACHE_DIR}"
rm -rf "${ROOT_DIR}/thirdparty"
ln -s "${THIRD_PARTY_CACHE_DIR}" "${ROOT_DIR}/thirdparty"

(
    flock 9
    if [ -f "${READY_MARKER}" ] &&
        [ -d "${THIRD_PARTY_CACHE_DIR}/boost/lib" ] &&
        [ -d "${THIRD_PARTY_CACHE_DIR}/libboundscheck/include" ]; then
        echo "Using cached SDK thirdparty for ${CACHE_ARCH}: ${THIRD_PARTY_CACHE_DIR}"
        exit 0
    fi

    echo "Preparing SDK thirdparty cache for ${CACHE_ARCH}: ${THIRD_PARTY_CACHE_DIR}"
    rm -f "${READY_MARKER}"
    download_sdk_thirdparty_sources
    compile_boost_libs
    touch "${READY_MARKER}"
) 9>"${THIRD_PARTY_LOCK}"
