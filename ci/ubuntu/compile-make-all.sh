#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(git -C "${SCRIPT_DIR}" rev-parse --show-toplevel)}"
CONTAINER_NAME="${CONTAINER_NAME:-compile}"
HOST_USER="${USER:-$(id -un)}"
COMPILE_USER="${COMPILE_USER:-${HOST_USER}}"
COMPILE_HOME="${COMPILE_HOME:-${HOME}}"
COMPILE_NETWORK="${COMPILE_NETWORK:-yr-net}"
START_CONTAINER="${START_CONTAINER:-true}"

default_compile_memory_limit() {
    local mem_kb mem_gb limit_gb
    mem_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
    if [[ "${mem_kb}" -le 0 ]]; then
        echo "32g"
        return
    fi

    mem_gb=$(( mem_kb / 1024 / 1024 ))
    limit_gb=$(( mem_gb * 80 / 100 ))
    (( limit_gb > 32 )) && limit_gb=32
    (( limit_gb < 8 )) && limit_gb=8
    echo "${limit_gb}g"
}

COMPILE_MEMORY_LIMIT="${COMPILE_MEMORY_LIMIT:-$(default_compile_memory_limit)}"
export COMPILE_MEMORY_LIMIT

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<EOF
Usage: $0 [make arguments...]

Runs make inside the compile container as the selected compile user.

Defaults:
  $0 all

Environment:
  CONTAINER_NAME      Docker container name. Default: compile
  COMPILE_USER        User used inside the container. Default: current user
  COMPILE_HOME        Host directory mounted into the container. Default: current HOME
  COMPILE_NETWORK     External docker network used by compose. Default: yr-net
  COMPILE_MEMORY_LIMIT Docker memory limit for the compile container. Default: 80% host memory, capped at 32g
  REPO_DIR            Repository path inside the container. Default: current git root
  START_CONTAINER     Start ci/ubuntu docker compose service if needed. Default: true
  JOBS                Optional make JOBS value
  REMOTE_CACHE        Optional make REMOTE_CACHE value
  BUILD_VERSION       Optional make BUILD_VERSION value
EOF
    exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required but was not found in PATH" >&2
    exit 1
fi

container_exists() {
    docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1
}

container_running() {
    [[ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null || true)" == "true" ]]
}

ensure_compile_container() {
    docker network inspect "${COMPILE_NETWORK}" >/dev/null 2>&1 || docker network create "${COMPILE_NETWORK}" >/dev/null
    COMPILE_USER="${COMPILE_USER}" COMPILE_HOME="${COMPILE_HOME}" COMPILE_NETWORK="${COMPILE_NETWORK}" \
        COMPILE_MEMORY_LIMIT="${COMPILE_MEMORY_LIMIT}" \
        docker compose -f "${SCRIPT_DIR}/docker-compose.yml" up -d
}

if [[ "${START_CONTAINER}" == "true" ]]; then
    ensure_compile_container
elif ! container_exists || ! container_running; then
    echo "Container ${CONTAINER_NAME} is not running; set START_CONTAINER=true or start it manually." >&2
    exit 1
fi

if ! docker exec "${CONTAINER_NAME}" getent passwd "${COMPILE_USER}" >/dev/null 2>&1; then
    echo "User ${COMPILE_USER} does not exist in container ${CONTAINER_NAME}." >&2
    exit 1
fi

container_uid="$(docker exec "${CONTAINER_NAME}" id -u "${COMPILE_USER}")"
container_gid="$(docker exec "${CONTAINER_NAME}" id -g "${COMPILE_USER}")"
exec_user="${container_uid}:${container_gid}"
container_home="$(docker exec "${CONTAINER_NAME}" getent passwd "${COMPILE_USER}" | awk -F: '{print $6}')"
if [[ -z "${container_home}" ]]; then
    container_home="${COMPILE_HOME}"
fi

if ! docker exec -u "${exec_user}" "${CONTAINER_NAME}" test -f "${REPO_DIR}/Makefile"; then
    echo "Repository ${REPO_DIR} is not visible inside container ${CONTAINER_NAME}." >&2
    echo "Set COMPILE_HOME to a parent directory that contains the repository, then rerun this script." >&2
    exit 1
fi

make_args=("$@")
if [[ ${#make_args[@]} -eq 0 ]]; then
    make_args=(all)
fi

[[ -n "${JOBS:-}" ]] && make_args+=("JOBS=${JOBS}")
[[ -n "${REMOTE_CACHE:-}" ]] && make_args+=("REMOTE_CACHE=${REMOTE_CACHE}")
[[ -n "${BUILD_VERSION:-}" ]] && make_args+=("BUILD_VERSION=${BUILD_VERSION}")

printf 'Running in container %s as %s: make' "${CONTAINER_NAME}" "${COMPILE_USER}"
printf ' %q' "${make_args[@]}"
printf '\n'

quoted_repo_dir="$(printf '%q' "${REPO_DIR}")"
quoted_make_args="$(printf ' %q' "${make_args[@]}")"

docker exec \
    -u "${exec_user}" \
    -e HOME="${container_home}" \
    -e USER="${COMPILE_USER}" \
    -w "${REPO_DIR}" \
    "${CONTAINER_NAME}" \
    bash -lc "set -euo pipefail; source /etc/profile.d/buildtools.sh 2>/dev/null || true; cd ${quoted_repo_dir}; exec make${quoted_make_args}"
