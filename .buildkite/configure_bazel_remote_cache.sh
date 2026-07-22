#!/usr/bin/env bash

# Source this file so REMOTE_CACHE remains available to the calling build.
# Linux Buildkite jobs use the shared action cache by default; callers can opt
# out explicitly with YR_BUILDKITE_ENABLE_BAZEL_REMOTE_CACHE=false.
BAZEL_REMOTE_URL="${BAZEL_REMOTE_URL:-grpc://bazel-remote.build-tools.svc.cluster.local:9092}"

case "${YR_BUILDKITE_ENABLE_BAZEL_REMOTE_CACHE:-true}" in
    1|true|TRUE|yes|YES|on|ON) _YR_BAZEL_REMOTE_ENABLED=1 ;;
    *) _YR_BAZEL_REMOTE_ENABLED=0 ;;
esac

echo "=== Configuring bazel-remote cache ==="
if [ "${_YR_BAZEL_REMOTE_ENABLED}" = "1" ] && \
    timeout 5 bash -c "echo > /dev/tcp/bazel-remote.build-tools.svc.cluster.local/9092" 2>/dev/null; then
    echo "bazel-remote reachable: ${BAZEL_REMOTE_URL}"
    export REMOTE_CACHE="${BAZEL_REMOTE_URL}"
elif [ "${_YR_BAZEL_REMOTE_ENABLED}" = "1" ]; then
    unset REMOTE_CACHE
    echo "WARNING: bazel-remote not reachable, building without remote cache"
else
    unset REMOTE_CACHE
    echo "bazel-remote explicitly disabled"
fi

unset _YR_BAZEL_REMOTE_ENABLED
