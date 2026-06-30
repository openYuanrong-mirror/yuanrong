#!/usr/bin/env bash
set -euo pipefail

# 设置镜像名称
IMAGE_NAME="${IMAGE_NAME:-swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev/compile-ubuntu2004}"
TAG="${TAG:-latest}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
PUSH="${PUSH:-true}"

# 确保 buildx 构建器已就绪
BUILDER_NAME="multiarch-builder"
if ! docker buildx inspect "$BUILDER_NAME" > /dev/null 2>&1; then
    echo "Creating new buildx builder: $BUILDER_NAME"
    docker buildx create --name "$BUILDER_NAME" --driver docker-container --use
    docker buildx inspect --bootstrap
else
    docker buildx use "$BUILDER_NAME"
fi

# 禁用 SWR 不支持的 Provenance 和 SBOM
export BUILDX_NO_DEFAULT_ATTESTATIONS=1

echo "Starting multi-arch build for $IMAGE_NAME:$TAG..."

push_arg=()
if [[ "$PUSH" == "true" ]]; then
  push_arg=(--push)
else
  push_arg=(--load)
fi

docker buildx build --platform "$PLATFORMS" \
  -t "$IMAGE_NAME:$TAG" \
  -f Dockerfile.ubuntu2004 \
  --provenance=false \
  --sbom=false \
  "${push_arg[@]}" .

echo "Build and push completed!"
