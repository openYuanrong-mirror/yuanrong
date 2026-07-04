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
"""Build the ``openyuanrong-rrt`` wheel: the Rust sandbox runtime binary
(``rrt-runtime``) packaged as a Python-version-agnostic, platform-specific
wheel (``py3-none-<platform>``), built once per platform.

The binary is copied from ``RRT_RUNTIME_SRC`` (default: the bazel build output)
into the package before wheeling. Name/version mirror the SDK so the SDK can pin
``Requires-Dist: openyuanrong-rrt==<BUILD_VERSION>``.
"""

import os
import platform
import shutil
import stat

import setuptools

try:
    from packaging import tags
except ImportError:  # pragma: no cover
    from wheel.vendored.packaging import tags

from wheel.bdist_wheel import bdist_wheel as _bdist_wheel

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.join(ROOT_DIR, "openyuanrong_rrt")
BINARY_NAME = "rrt-runtime"

BASE_NAME = os.getenv("YR_PACKAGE_NAME", "openyuanrong")
PACKAGE_NAME = f"{BASE_NAME}-rrt"

DEFAULT_RRT_SRC = os.path.join(
    ROOT_DIR, "../../build/output/runtime/service/rust/bin", BINARY_NAME
)


def get_version():
    version = os.getenv("BUILD_VERSION", "").strip()
    if version:
        return version
    return open(os.path.join(ROOT_DIR, "../../VERSION")).read().strip()


def stage_binary():
    """Copy the prebuilt rrt-runtime binary into the package dir (chmod +x)."""
    src = os.path.abspath(os.getenv("RRT_RUNTIME_SRC", DEFAULT_RRT_SRC))
    if not os.path.isfile(src):
        raise FileNotFoundError(
            f"rrt-runtime binary not found at {src}; build //api/rust first or set "
            "RRT_RUNTIME_SRC."
        )
    dst = os.path.join(PKG_DIR, BINARY_NAME)
    shutil.copyfile(src, dst)
    mode = os.stat(dst).st_mode
    os.chmod(dst, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def get_wheel_platform_tag():
    """macOS arm64 needs an explicit tag; otherwise use the host platform tag."""
    is_macos_arm64 = platform.system() == "Darwin" and platform.machine() in {
        "arm64",
        "aarch64",
    }
    if not is_macos_arm64:
        return None
    target = os.getenv("MACOSX_DEPLOYMENT_TARGET", "").strip() or "11.0"
    major, _, minor = target.partition(".")
    minor = minor or "0"
    return f"macosx_{major}_{minor or '0'}_arm64"


class BdistWheelImpl(_bdist_wheel):
    """Force a py3-none-<platform> tag: the binary is arch-specific but not
    Python-version/ABI specific."""

    def get_tag(self):
        host = next(tags.sys_tags())
        platform_tag = get_wheel_platform_tag() or host.platform
        return "py3", "none", platform_tag


class BinaryDistribution(setuptools.Distribution):
    """Mark the distribution as platform-specific (carries a native binary)."""

    def __init__(self, attrs=None):
        super().__init__(attrs)
        self.metadata.metadata_version = "2.2"

    def has_ext_modules(self):
        return True


stage_binary()

setuptools.setup(
    name=PACKAGE_NAME,
    version=get_version(),
    author="openyuanrong",
    description="openYuanrong Rust sandbox runtime (rrt-runtime) binary",
    python_requires=">=3.9,<3.14",
    cmdclass={"bdist_wheel": BdistWheelImpl},
    # BinaryDistribution.has_ext_modules() forces a platform (non-purelib) wheel;
    # BdistWheelImpl.get_tag() pins it to py3-none-<platform>.
    distclass=BinaryDistribution,
    packages=["openyuanrong_rrt"],
    include_package_data=False,
    package_data={"openyuanrong_rrt": [BINARY_NAME]},
)
