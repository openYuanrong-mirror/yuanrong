#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Buildkite Agent 快速设置脚本（macOS 裸机版包装）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAC_SCRIPT="${SCRIPT_DIR}/install-buildkite-agent-macos.sh"

if [[ ! -f "${MAC_SCRIPT}" ]]; then
    echo "[ERROR] 缺少脚本: ${MAC_SCRIPT}" >&2
    exit 1
fi

exec bash "${MAC_SCRIPT}" "$@"
