#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${ROOT_DIR}/../../.." && pwd)"
OUTPUT_DIR="${REPO_ROOT}/output"
DOCKER_BIN="${DOCKER_BIN:-docker}"
CONTROLPLANE_IMAGE="${YR_CONTROLPLANE_IMAGE:-yr-controlplane}"
NODE_IMAGE="${YR_NODE_IMAGE:-yr-node}"
RUNTIME_IMAGE="${YR_RUNTIME_IMAGE:-yr-runtime}"

required_patterns=(
  "openyuanrong-*.whl"
  "openyuanrong_sdk*.whl"
)

artifact_candidate_dirs=()
python_build_args=()

resolve_single_artifact() {
  local source_dir="$1"
  local pattern="$2"
  local matches=()

  mapfile -t matches < <(find "${source_dir}" -maxdepth 1 -type f -name "${pattern}" -printf '%p\n' | sort -V)
  if [ "${#matches[@]}" -eq 0 ]; then
    return 1
  fi
  if [ "${#matches[@]}" -ne 1 ]; then
    printf 'Expected exactly one artifact matching %s in %s, found %s\n' "${pattern}" "${source_dir}" "${#matches[@]}" >&2
    printf '%s\n' "${matches[@]}" >&2
    exit 1
  fi

  printf '%s\n' "${matches[0]}"
}

build_candidate_dirs() {
  local candidate_dir

  artifact_candidate_dirs+=("${OUTPUT_DIR}")
}

resolve_artifact_path() {
  local pattern="$1"
  local candidate_dir

  for candidate_dir in "${artifact_candidate_dirs[@]}"; do
    [ -d "${candidate_dir}" ] || continue
    if resolve_single_artifact "${candidate_dir}" "${pattern}" >/dev/null; then
      resolve_single_artifact "${candidate_dir}" "${pattern}"
      return 0
    fi
  done

  return 1
}

validate_required_artifacts() {
  local pattern

  for pattern in "${required_patterns[@]}"; do
    if ! resolve_artifact_path "${pattern}" >/dev/null; then
      printf 'Missing required artifact matching %s in candidate directories.\n' "${pattern}" >&2
      printf 'Checked: %s\n' "${artifact_candidate_dirs[*]}" >&2
      printf 'Fail-fast: staged artifact not found. Run: make all\n' >&2
      exit 1
    fi
  done
}

python_build_args_from_wheel() {
  local wheel_path="$1"
  local wheel_name
  local python_tag
  wheel_name="$(basename "${wheel_path}")"

  if [[ ! "${wheel_name}" =~ -(cp[0-9]+)- ]]; then
    printf 'Cannot infer Python ABI tag from wheel: %s\n' "${wheel_name}" >&2
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
      printf 'Unsupported Python ABI tag in wheel: %s\n' "${python_tag}" >&2
      exit 1
      ;;
  esac
}

set_python_build_args() {
  local sdk_wheel
  sdk_wheel="$(resolve_artifact_path "openyuanrong_sdk*.whl")"
  mapfile -t python_build_args < <(python_build_args_from_wheel "${sdk_wheel}")
}

build_image() {
  local image_name="$1"
  local dockerfile_path="$2"
  shift 2

  printf 'Building %s from %s\n' "${image_name}" "${dockerfile_path}" >&2
  DOCKER_BUILDKIT=1 "${DOCKER_BIN}" build \
    -t "${image_name}" \
    --build-arg PYTHON_VERSION="${python_build_args[0]}" \
    --build-arg PYTHON_MAJOR_MINOR="${python_build_args[1]}" \
    --build-context deploy="${ROOT_DIR}" \
    -f "${ROOT_DIR}/${dockerfile_path}" \
    "$@" \
    "${OUTPUT_DIR}"
}

main() {
  if ! command -v "${DOCKER_BIN}" >/dev/null 2>&1; then
    printf 'Missing container build CLI: %s\n' "${DOCKER_BIN}" >&2
    printf 'Fail-fast: docker build entrypoint cannot run without a working container CLI.\n' >&2
    exit 1
  fi

  printf 'yr-k8s build entrypoint: using output artifacts and building docker images from %s.\n' "${OUTPUT_DIR}" >&2
  printf 'If a required artifact is missing, fail-fast and run: make all\n' >&2

  build_candidate_dirs
  validate_required_artifacts
  set_python_build_args

  build_image "${CONTROLPLANE_IMAGE}" "images/Dockerfile.controlplane-base"
  build_image "${NODE_IMAGE}" "images/Dockerfile.node" \
    --build-arg CONTROLPLANE_IMAGE="${CONTROLPLANE_IMAGE}"
  build_image "${RUNTIME_IMAGE}" "images/Dockerfile.runtime" \
    --build-arg CONTROLPLANE_IMAGE="${CONTROLPLANE_IMAGE}"

  printf 'Image builds completed: %s, %s, %s\n' \
    "${CONTROLPLANE_IMAGE}" \
    "${NODE_IMAGE}" \
    "${RUNTIME_IMAGE}" >&2
}

main "$@"
