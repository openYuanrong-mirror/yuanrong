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

import os
import platform


MACOS_ARM64_PLATFORM_TAG = "macosx_11_0_arm64"


def _is_macos_arm64():
    return platform.system() == "Darwin" and platform.machine() in {"arm64", "aarch64"}


def get_macos_deployment_target(default="11.0"):
    deployment_target = os.getenv("MACOSX_DEPLOYMENT_TARGET", "").strip()
    return deployment_target or default


def _normalize_macos_target_components(deployment_target):
    parts = deployment_target.split(".")
    major = parts[0]
    minor = parts[1] if len(parts) > 1 else "0"
    if not major.isdigit() or not minor.isdigit():
        raise ValueError(f"Invalid MACOSX_DEPLOYMENT_TARGET: {deployment_target}")
    return major, minor


def get_wheel_platform_tag():
    if not _is_macos_arm64():
        return None
    deployment_target = get_macos_deployment_target()
    if deployment_target == "11.0":
        return MACOS_ARM64_PLATFORM_TAG
    major, minor = _normalize_macos_target_components(deployment_target)
    return f"macosx_{major}_{minor}_arm64"
