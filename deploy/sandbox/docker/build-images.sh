#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
SANDBOX_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUTPUT_DIR="${REPO_ROOT}/output"
BASE_IMAGE="${YR_BASE_IMAGE:-yr-base}"
COMPILE_IMAGE="${YR_COMPILE_IMAGE:-yr-compile}"
CONTROLPLANE_IMAGE="${YR_CONTROLPLANE_IMAGE:-yr-controlplane}"
RUNTIME_IMAGE="${YR_RUNTIME_IMAGE:-aio-yr-runtime}"
AIO_IMAGE="${YR_AIO_IMAGE:-aio-yr}"
RUNTIME_TAR="${OUTPUT_DIR}/aio-yr-runtime.tar"
required_files=(
    "${OUTPUT_DIR}/runtime-launcher"
)

resolve_single_file() {
    local pattern="$1"
    local matches=()

    mapfile -t matches < <(compgen -G "${pattern}" | sort -V)
    if [ "${#matches[@]}" -eq 0 ]; then
        return 1
    fi
    if [ "${#matches[@]}" -ne 1 ]; then
        echo "Expected exactly one artifact matching ${pattern}, found ${#matches[@]}" >&2
        printf '%s\n' "${matches[@]}" >&2
        exit 1
    fi

    printf '%s\n' "${matches[0]}"
}

python_build_args_from_wheel() {
    local wheel_path="$1"
    local wheel_name
    local python_tag
    wheel_name="$(basename "${wheel_path}")"

    if [[ ! "${wheel_name}" =~ -(cp[0-9]+)- ]]; then
        echo "Cannot infer Python ABI tag from wheel: ${wheel_name}" >&2
        exit 1
    fi
    python_tag="${BASH_REMATCH[1]}"

    case "${python_tag}" in
        cp39)
            printf '%s\n' "3.9.18" "3.9"
            ;;
        cp310)
            printf '%s\n' "3.10.13" "3.10"
            ;;
        cp311)
            printf '%s\n' "3.11.9" "3.11"
            ;;
        *)
            echo "Unsupported Python ABI tag in wheel: ${python_tag}" >&2
            exit 1
            ;;
    esac
}

for required_file in "${required_files[@]}"; do
    if [ ! -e "${required_file}" ]; then
        echo "Missing required build artifact: ${required_file}" >&2
        echo "Run: make all" >&2
        exit 1
    fi
done

if ! resolve_single_file "${OUTPUT_DIR}/openyuanrong-*.whl" >/dev/null; then
    echo "Missing required build artifact: ${OUTPUT_DIR}/openyuanrong-*.whl" >&2
    echo "Run: make all" >&2
    exit 1
fi

if ! resolve_single_file "${OUTPUT_DIR}/openyuanrong_sdk*.whl" >/dev/null; then
    echo "Missing required build artifact: ${OUTPUT_DIR}/openyuanrong_sdk-*.whl" >&2
    echo "Run: make all" >&2
    exit 1
fi

sdk_wheel="$(resolve_single_file "${OUTPUT_DIR}/openyuanrong_sdk*.whl")"
mapfile -t python_build_args < <(python_build_args_from_wheel "${sdk_wheel}")
python_version="${python_build_args[0]}"
python_major_minor="${python_build_args[1]}"

mkdir -p "${OUTPUT_DIR}"
DOCKER_BUILDKIT=1 docker build \
    --build-arg PYTHON_VERSION="${python_version}" \
    --build-arg PYTHON_MAJOR_MINOR="${python_major_minor}" \
    -f "${SANDBOX_DIR}/images/Dockerfile.base" \
    -t "${BASE_IMAGE}:latest" \
    "${OUTPUT_DIR}"
DOCKER_BUILDKIT=1 docker build \
    --build-arg PYTHON_VERSION="${python_version}" \
    --build-arg PYTHON_MAJOR_MINOR="${python_major_minor}" \
    --build-arg BASE_IMAGE="${BASE_IMAGE}:latest" \
    -f "${SANDBOX_DIR}/images/Dockerfile.compile" \
    -t "${COMPILE_IMAGE}:latest" \
    "${OUTPUT_DIR}"
DOCKER_BUILDKIT=1 docker build \
    --build-arg PYTHON_VERSION="${python_version}" \
    --build-arg PYTHON_MAJOR_MINOR="${python_major_minor}" \
    --build-arg BASE_IMAGE="${BASE_IMAGE}:latest" \
    --build-context deploy="${SANDBOX_DIR}/k8s" \
    -f "${SANDBOX_DIR}/k8s/images/Dockerfile.controlplane-base" \
    -t "${CONTROLPLANE_IMAGE}:latest" \
    "${OUTPUT_DIR}"
DOCKER_BUILDKIT=1 docker build \
    --build-arg PYTHON_VERSION="${python_version}" \
    --build-arg PYTHON_MAJOR_MINOR="${python_major_minor}" \
    --build-arg BASE_IMAGE="${BASE_IMAGE}:latest" \
    -f "${SCRIPT_DIR}/Dockerfile.runtime" \
    -t "${RUNTIME_IMAGE}:latest" \
    "${OUTPUT_DIR}"
docker save "${RUNTIME_IMAGE}:latest" -o "${RUNTIME_TAR}"
DOCKER_BUILDKIT=1 docker build \
    --build-arg PYTHON_VERSION="${python_version}" \
    --build-arg PYTHON_MAJOR_MINOR="${python_major_minor}" \
    --build-arg CONTROLPLANE_IMAGE="${CONTROLPLANE_IMAGE}:latest" \
    --build-context deploy="${SCRIPT_DIR}" \
    -f "${SCRIPT_DIR}/Dockerfile.aio-yr" \
    -t "${AIO_IMAGE}:latest" \
    "${OUTPUT_DIR}"
