#!/bin/bash
# 准备多架构工具包
set -e
mkdir -p ci/ubuntu/tools/amd64 ci/ubuntu/tools/arm64

# --- 下载 amd64 工具 ---
echo "Downloading amd64 tools..."
# Go
[ -f ci/ubuntu/tools/amd64/go.tar.gz ] || wget -q https://dl.google.com/go/go1.24.1.linux-amd64.tar.gz -O ci/ubuntu/tools/amd64/go.tar.gz
# Bazel
[ -f ci/ubuntu/tools/amd64/bazel ] || wget -q https://github.com/bazelbuild/bazel/releases/download/6.5.0/bazel-6.5.0-linux-x86_64 -O ci/ubuntu/tools/amd64/bazel
# CMake
[ -f ci/ubuntu/tools/amd64/cmake.sh ] || wget -q https://github.com/Kitware/CMake/releases/download/v3.28.1/cmake-3.28.1-linux-x86_64.sh -O ci/ubuntu/tools/amd64/cmake.sh
# Protoc
[ -f ci/ubuntu/tools/amd64/protoc.zip ] || wget -q https://github.com/protocolbuffers/protobuf/releases/download/v25.1/protoc-25.1-linux-x86_64.zip -O ci/ubuntu/tools/amd64/protoc.zip

# --- 下载 arm64 工具 ---
echo "Downloading arm64 tools..."
# Go
[ -f ci/ubuntu/tools/arm64/go.tar.gz ] || wget -q https://dl.google.com/go/go1.24.1.linux-arm64.tar.gz -O ci/ubuntu/tools/arm64/go.tar.gz
# Bazel
[ -f ci/ubuntu/tools/arm64/bazel ] || wget -q https://github.com/bazelbuild/bazel/releases/download/6.5.0/bazel-6.5.0-linux-aarch64 -O ci/ubuntu/tools/arm64/bazel
# CMake
[ -f ci/ubuntu/tools/arm64/cmake.sh ] || wget -q https://github.com/Kitware/CMake/releases/download/v3.28.1/cmake-3.28.1-linux-aarch64.sh -O ci/ubuntu/tools/arm64/cmake.sh
# Protoc
[ -f ci/ubuntu/tools/arm64/protoc.zip ] || wget -q https://github.com/protocolbuffers/protobuf/releases/download/v25.1/protoc-25.1-linux-aarch64.zip -O ci/ubuntu/tools/arm64/protoc.zip

echo "All tools downloaded successfully!"
