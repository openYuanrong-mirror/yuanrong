#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd "$(dirname "$0")" && pwd)
gateway_dir=$(cd "${script_dir}/.." && pwd)
repo_root=$(cd "${gateway_dir}/.." && pwd)

arch=${YR_DATA_PLANE_ARCH:-}
if [ -z "$arch" ]; then
    case "$(uname -m)" in
        x86_64|amd64) arch=amd64 ;;
        arm64|aarch64) arch=arm64 ;;
        *) echo "unsupported build architecture: $(uname -m)" >&2; exit 1 ;;
    esac
fi

case "$arch" in
    amd64) target=x86_64-unknown-linux-musl ;;
    arm64) target=aarch64-unknown-linux-musl ;;
    *) echo "YR_DATA_PLANE_ARCH must be amd64 or arm64" >&2; exit 2 ;;
esac

output_dir=${YR_DATA_PLANE_OUTPUT_DIR:-${repo_root}/build/output/data_plane/bin}
image=${YR_DATA_PLANE_STATIC_BUILDER_IMAGE:-yr-data-plane-static-builder:1.88-${arch}}
platform=linux/${arch}

docker build \
    --platform "$platform" \
    --build-arg "RUST_TARGET=${target}" \
    -t "$image" \
    -f "${gateway_dir}/tests/aio_3node/Dockerfile.static-builder" \
    "${gateway_dir}/tests/aio_3node"

mkdir -p "$output_dir"
docker run --rm --platform "$platform" \
    -v "${gateway_dir}:/workspace" \
    -v "${output_dir}:/out" \
    -v yr-data-plane-cargo-home:/cargo \
    -v "yr-data-plane-static-target-${arch}:/target" \
    -e CARGO_HOME=/cargo \
    -e CARGO_TARGET_DIR=/target \
    -e CC=musl-gcc \
    -e CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER=musl-gcc \
    -e CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER=musl-gcc \
    -w /workspace \
    "$image" \
    bash -euo pipefail -c '
        find /out -mindepth 1 -maxdepth 1 -type f -delete
        export RUSTFLAGS="${RUSTFLAGS:+${RUSTFLAGS} }-C target-feature=+crt-static -C link-self-contained=yes -C relocation-model=static"
        cargo --config '\''source.crates-io.replace-with="rsproxy-sparse"'\'' \
            --config '\''source.rsproxy-sparse.registry="sparse+https://rsproxy.cn/index/"'\'' \
            build --locked --release --all-features --bins --target '"$target"'
        for binary in yr-node-proxy yr-edge-frontend yr-data-plane-forward; do
            strip "/target/'"$target"'/release/${binary}"
            install -m 0755 "/target/'"$target"'/release/${binary}" "/out/${binary}"
        done
        scripts/verify-static-linux.sh /out/yr-node-proxy /out/yr-edge-frontend /out/yr-data-plane-forward
    '

"${script_dir}/verify-static-linux.sh" \
    "${output_dir}/yr-node-proxy" \
    "${output_dir}/yr-edge-frontend" \
    "${output_dir}/yr-data-plane-forward"
