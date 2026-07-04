#!/usr/bin/env python3
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""openyuanrong-rrt: the Rust sandbox runtime (rrt-runtime) shipped as a
Python-version-agnostic, platform-specific wheel.

The binary itself is architecture-specific but does NOT depend on the Python
version/ABI (it is exec'd as a subprocess, never imported), so it is built once
per platform and pinned by the SDK via ``Requires-Dist: openyuanrong-rrt==<ver>``
instead of being duplicated into every cpXX SDK wheel.

Consumers resolve the binary via :func:`runtime_path` (track A, pip). The same
bytes are also published as a bare binary for non-pip / bare-rootfs consumers
(track B); see ``RRT_RUNTIME_BIN`` for an explicit override.
"""

import os

__all__ = ["runtime_path", "RRT_BINARY_NAME"]

RRT_BINARY_NAME = "rrt-runtime"


def runtime_path() -> str:
    """Return the absolute path to the bundled ``rrt-runtime`` binary.

    Resolution order (lets one entrypoint serve both delivery tracks):
      1. ``RRT_RUNTIME_BIN`` env override (explicit path), else
      2. the bundled binary inside this package (pip / track A).
    """
    override = os.environ.get("RRT_RUNTIME_BIN", "").strip()
    if override:
        return override
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), RRT_BINARY_NAME)
