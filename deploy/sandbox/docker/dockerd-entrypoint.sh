#!/usr/bin/env bash

set -euo pipefail

DOCKER_SOCKET="${DOCKER_HOST:-unix:///var/run/docker.sock}"
DOCKERD_LOG="${DOCKERD_LOG:-/var/log/dockerd.log}"
DOCKER_READY_TIMEOUT="${DOCKER_READY_TIMEOUT:-60}"
DOCKER_DRIVER="${DOCKER_DRIVER:-overlay2}"

mkdir -p /var/lib/docker /var/log /var/run

start_dockerd() {
    local storage_driver="$1"
    : >"${DOCKERD_LOG}"
    dockerd --host="${DOCKER_SOCKET}" --storage-driver="${storage_driver}" >"${DOCKERD_LOG}" 2>&1 &
    DOCKERD_PID=$!
}

wait_for_dockerd() {
    local storage_driver="$1"
    for _ in $(seq 1 "${DOCKER_READY_TIMEOUT}"); do
        if docker info >/dev/null 2>&1; then
            return 0
        fi
        if ! kill -0 "${DOCKERD_PID}" >/dev/null 2>&1; then
            return 1
        fi
        sleep 1
    done
    echo "dockerd did not become ready within ${DOCKER_READY_TIMEOUT}s using ${storage_driver}" >&2
    return 1
}

start_dockerd "${DOCKER_DRIVER}"
if wait_for_dockerd "${DOCKER_DRIVER}"; then
    wait "${DOCKERD_PID}"
    exit $?
fi

cat "${DOCKERD_LOG}" >&2 || true

if [[ "${DOCKER_DRIVER}" == "overlay2" ]]; then
    echo "dockerd failed with overlay2, retrying with vfs" >&2
    kill "${DOCKERD_PID}" 2>/dev/null || true
    wait "${DOCKERD_PID}" 2>/dev/null || true
    start_dockerd "vfs"
    if wait_for_dockerd "vfs"; then
        wait "${DOCKERD_PID}"
        exit $?
    fi
    cat "${DOCKERD_LOG}" >&2 || true
fi

exit 1
