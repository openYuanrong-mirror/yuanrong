#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${1:-${ROOT_DIR}/output}"
SDK_PYTHON_VERSIONS="${SDK_PYTHON_VERSIONS:-python3.9 python3.10 python3.11 python3.12}"
BUILD_VERSION="${BUILD_VERSION:-$(cat "${ROOT_DIR}/VERSION")}"
BOOST_VERSION="${BOOST_VERSION:-1.87.0}"
SDK_BAZEL_JOBS="${SDK_BAZEL_JOBS:-8}"
SDK_BAZEL_BUILD_ROOT="${SDK_BAZEL_BUILD_ROOT:-${ROOT_DIR}/build/sdk-${BUILDKITE_JOB_ID:-local}}"

case "${OUTPUT_DIR}" in
    /*) ;;
    *) OUTPUT_DIR="${ROOT_DIR}/${OUTPUT_DIR}" ;;
esac

resolve_sdk_python() {
    local py_version="$1"
    local py_minor="${py_version#python}"
    local py_env="py${py_minor//./}"
    local conda_root="${CONDA_PREFIX:-${HOME}/miniforge3}"
    local candidate

    for candidate in \
        "${py_version}" \
        "/opt/buildtools/${py_version}/bin/${py_version}" \
        "${conda_root}/bin/${py_version}" \
        "${conda_root}/envs/${py_env}/bin/${py_version}" \
        "${conda_root}/envs/yuanrong/bin/${py_version}" \
        "/opt/homebrew/opt/python@${py_minor}/bin/${py_version}" \
        "/usr/local/opt/python@${py_minor}/bin/${py_version}"; do
        if command -v "${candidate}" >/dev/null 2>&1; then
            command -v "${candidate}"
            return 0
        fi
        if [ -x "${candidate}" ]; then
            printf '%s\n' "${candidate}"
            return 0
        fi
    done
    if [ -d "${conda_root}/envs" ]; then
        candidate="$(find "${conda_root}/envs" -maxdepth 3 -type f -path "*/bin/${py_version}" 2>/dev/null | sort | head -1)"
        if [ -n "${candidate}" ] && [ -x "${candidate}" ]; then
            printf '%s\n' "${candidate}"
            return 0
        fi
    fi

    printf 'Missing SDK Python interpreter: %s\n' "${py_version}" >&2
    exit 1
}

pip_flags_for_python() {
    local python_bin="$1"
    if "${python_bin}" -m pip install --help 2>/dev/null | grep -q -- '--break-system-packages'; then
        printf '%s\n' '--break-system-packages'
    fi
}

ensure_sdk_python_packages() {
    local python_bin="$1"
    local pip_flag

    if "${python_bin}" -c 'import packaging, wheel' >/dev/null 2>&1; then
        return 0
    fi

    pip_flag="$(pip_flags_for_python "${python_bin}")"
    "${python_bin}" -m pip install ${pip_flag:+${pip_flag}} -q --retries 2 --timeout 60 \
        --index-url "${PIP_INDEX_URL:-https://mirrors.huaweicloud.com/repository/pypi/simple}" \
        --trusted-host "${PIP_TRUSTED_HOST:-mirrors.huaweicloud.com}" \
        packaging wheel
}

build_sdk_wheel() {
    local py_version="$1"
    local python_bin="$2"
    local output_root="${SDK_BAZEL_BUILD_ROOT}/${py_version}"

    ensure_sdk_python_packages "${python_bin}"

    BAZEL_OUTPUT_USER_ROOT="${output_root}" \
        BAZEL_OUTPUT_BASE="${output_root}/output" \
        bash "${ROOT_DIR}/build.sh" -p "${python_bin}" -v "${BUILD_VERSION}" -j "${SDK_BAZEL_JOBS}"
    if [ "${OUTPUT_DIR}" != "${ROOT_DIR}/output" ]; then
        cp -R "${ROOT_DIR}"/output/openyuanrong_sdk-"${BUILD_VERSION}"-*.whl "${OUTPUT_DIR}/"
    fi
}

main() {
    local py_version
    local python_bin

    mkdir -p "${OUTPUT_DIR}"
    for py_version in ${SDK_PYTHON_VERSIONS}; do
        python_bin="$(resolve_sdk_python "${py_version}")"
        printf 'Building openyuanrong-sdk for %s with %s\n' "${py_version}" "${python_bin}" >&2
        build_sdk_wheel "${py_version}" "${python_bin}"
    done
}

main "$@"
