#!/bin/bash

set -euo pipefail

if [[ $# -ne 4 ]]; then
    echo "Usage: $0 <api-dir> <output-dir> <python-bin> <runtime-python-version>" >&2
    exit 2
fi

API_DIR=$1
OUTPUT_DIR=$2
PYTHON_BIN=$3
RUNTIME_PYTHON_VERSION=$4
PYTHON_SOURCE_DIR="$API_DIR/python"
WHEEL_WORK_DIRS=()
HEAVY_PIDS=()

terminate_process_tree() {
    local parent_pid=$1
    local child_pid
    local child_pids

    child_pids=$(pgrep -P "$parent_pid" 2>/dev/null || true)
    for child_pid in $child_pids; do
        terminate_process_tree "$child_pid"
    done
    kill -TERM "$parent_pid" 2>/dev/null || true
}

cleanup_wheel_work_dirs() {
    local pid
    if [[ ${#HEAVY_PIDS[@]} -gt 0 ]]; then
        for pid in "${HEAVY_PIDS[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                terminate_process_tree "$pid"
            fi
        done
        for pid in "${HEAVY_PIDS[@]}"; do
            wait "$pid" 2>/dev/null || true
        done
    fi
    if [[ ${#WHEEL_WORK_DIRS[@]} -gt 0 ]]; then
        rm -rf "${WHEEL_WORK_DIRS[@]}"
    fi
}
trap cleanup_wheel_work_dirs EXIT

build_wheel_in_dir() {
    local setup_type=$1
    local work_dir=$2
    local label=${setup_type:-openyuanrong}
    local start

    rm -rf "$work_dir/build" "$work_dir/dist"
    find "$work_dir" -maxdepth 1 -name '*.egg-info' -exec rm -rf {} +
    start=$(date +%s)
    echo "[WHEEL_TIMER] START label=$label epoch=$start"
    (
        cd "$work_dir"
        SETUP_TYPE="$setup_type" \
            PYTHON_RUNTIME_VERSION="$RUNTIME_PYTHON_VERSION" \
            "$PYTHON_BIN" setup.py bdist_wheel
    )
    cp -R "$work_dir"/dist/*.whl "$OUTPUT_DIR/"
    echo "[WHEEL_TIMER] END label=$label elapsed=$(($(date +%s) - start))s"
}

build_isolated_wheel() {
    local setup_type=$1
    local work_dir=$2

    cp -a "$PYTHON_SOURCE_DIR/." "$work_dir/"
    build_wheel_in_dir "$setup_type" "$work_dir"
}

mkdir -p "$OUTPUT_DIR"

# Keep the small wheels sequential to avoid extra process and IO contention.
build_wheel_in_dir "" "$PYTHON_SOURCE_DIR"
build_wheel_in_dir "dashboard" "$PYTHON_SOURCE_DIR"
build_wheel_in_dir "faas" "$PYTHON_SOURCE_DIR"

heavy_setup_types=("sdk_cpp" "runtime" "full")
for setup_type in "${heavy_setup_types[@]}"; do
    work_dir=$(mktemp -d "$API_DIR/.python-wheel-${setup_type}.XXXXXX")
    WHEEL_WORK_DIRS+=("$work_dir")
    build_isolated_wheel "$setup_type" "$work_dir" &
    HEAVY_PIDS+=("$!")
done

status=0
for pid in "${HEAVY_PIDS[@]}"; do
    if ! wait "$pid"; then
        status=1
    fi
done
HEAVY_PIDS=()

exit "$status"
