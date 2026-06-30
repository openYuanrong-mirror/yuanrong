#!/usr/bin/env bash
set -euo pipefail

umask 0027

export CONTAINER_EP="${CONTAINER_EP:-unix:///var/run/runtime-launcher.sock}"
export DOCKER_HOST="${DOCKER_HOST:-unix:///var/run/docker.sock}"

mkdir -p /tmp/yr_sessions /var/log/supervisor /var/run
mkdir -p /var/lib/docker
rm -f /var/run/runtime-launcher.sock

DOCKERD_LOG="/var/log/dockerd.log"
DOCKER_DRIVER="${DOCKER_DRIVER:-overlay2}"
DOCKER_READY_TIMEOUT="${DOCKER_READY_TIMEOUT:-60}"
DOCKER_LOG_MAX_SIZE="${DOCKER_LOG_MAX_SIZE:-100m}"
DOCKER_LOG_MAX_FILE="${DOCKER_LOG_MAX_FILE:-3}"

DOCKERD_ARGS=(
    --host="${DOCKER_HOST}"
    --log-opt "max-size=${DOCKER_LOG_MAX_SIZE}"
    --log-opt "max-file=${DOCKER_LOG_MAX_FILE}"
)

: >"${DOCKERD_LOG}"
dockerd "${DOCKERD_ARGS[@]}" --storage-driver="${DOCKER_DRIVER}" >>"${DOCKERD_LOG}" 2>&1 &
DOCKERD_PID=$!

ready=0
for _ in $(seq 1 "${DOCKER_READY_TIMEOUT}"); do
    if docker info >/dev/null 2>&1; then
        ready=1
        break
    fi
    if ! kill -0 "${DOCKERD_PID}" 2>/dev/null; then
        break
    fi
    sleep 1
done

if [[ "${ready}" -eq 0 ]]; then
    kill "${DOCKERD_PID}" 2>/dev/null || true
    wait "${DOCKERD_PID}" 2>/dev/null || true
    : >"${DOCKERD_LOG}"
    dockerd "${DOCKERD_ARGS[@]}" --storage-driver=vfs >>"${DOCKERD_LOG}" 2>&1 &
    DOCKERD_PID=$!
    for _ in $(seq 1 "${DOCKER_READY_TIMEOUT}"); do
        if docker info >/dev/null 2>&1; then
            ready=1
            break
        fi
        sleep 1
    done
fi

if [[ "${ready}" -eq 0 ]]; then
    cat "${DOCKERD_LOG}" >&2
    exit 1
fi

exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf -n
