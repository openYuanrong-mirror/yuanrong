#!/usr/bin/env bash

set -euo pipefail

export CONTAINER_EP=unix:///var/run/runtime-launcher.sock
AIO_NODE_IP="$(hostname -i | awk '{print $1}')"

mkdir -p /tmp/yr_sessions
mkdir -p /var/log/supervisor
mkdir -p /var/lib/docker
mkdir -p /var/run

# Start dockerd in the background and wait until it is ready.
# We do NOT exec/wait on it here — supervisord will own the process tree.
DOCKER_SOCKET="${DOCKER_HOST:-unix:///var/run/docker.sock}"
DOCKERD_LOG="/var/log/dockerd.log"
DOCKER_DRIVER="${DOCKER_DRIVER:-overlay2}"
DOCKER_READY_TIMEOUT="${DOCKER_READY_TIMEOUT:-60}"

: >"${DOCKERD_LOG}"
dockerd --host="${DOCKER_SOCKET}" --storage-driver="${DOCKER_DRIVER}" \
    >>"${DOCKERD_LOG}" 2>&1 &
DOCKERD_PID=$!

echo "Waiting for dockerd (pid=${DOCKERD_PID}) to be ready..."
ready=0
for _ in $(seq 1 "${DOCKER_READY_TIMEOUT}"); do
    if docker info >/dev/null 2>&1; then
        ready=1
        break
    fi
    if ! kill -0 "${DOCKERD_PID}" 2>/dev/null; then
        echo "dockerd exited unexpectedly, retrying with fallback driver. Log:" >&2
        cat "${DOCKERD_LOG}" >&2
        break
    fi
    sleep 1
done

if [[ "${ready}" -eq 0 ]]; then
    # Retry with vfs storage driver
    echo "overlay2 driver failed, retrying with vfs..." >&2
    kill "${DOCKERD_PID}" 2>/dev/null || true
    wait "${DOCKERD_PID}" 2>/dev/null || true
    : >"${DOCKERD_LOG}"
    dockerd --host="${DOCKER_SOCKET}" --storage-driver=vfs \
        >>"${DOCKERD_LOG}" 2>&1 &
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
    echo "dockerd did not become ready. Log:" >&2
    cat "${DOCKERD_LOG}" >&2
    exit 1
fi

echo "dockerd is ready."

if ! docker image inspect aio-yr-runtime:latest >/dev/null 2>&1; then
    docker load -i /opt/runtime-images/aio-yr-runtime.tar >/dev/null
fi

sed -i "s/__AIO_NODE_IP__/${AIO_NODE_IP}/g" /openyuanrong/traefik/dynamic.yml /openyuanrong/traefik/traefik.yml

exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf -n
