#!/usr/bin/env bash
# Run a command inside the Rust compile-image container; workspace api/rust is mounted at /ws.
# Usage: bash api/rust/scripts/in-compile.sh "cargo build -p rrt-daemon"
set -euo pipefail
IMG="swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev/compile-ubuntu2004-rust:v20260507_x86_64"
WS="$(cd "$(dirname "$0")/.." && pwd)"
docker run --rm \
  -v "$WS":/ws -w /ws \
  -e CARGO_HOME=/ws/.cargo-home \
  "$IMG" bash -lc "$*"
