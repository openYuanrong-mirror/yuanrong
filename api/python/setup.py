#!/usr/bin/env python3
# coding=UTF-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
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

"""setup for openyuanrong Python packages."""

from enum import Enum
import os
import shutil
import sysconfig
import tempfile
import warnings
import zipfile

import setuptools
from setuptools.command.build_ext import build_ext
from setuptools.command.build_py import build_py
from setuptools.command.develop import develop
from setuptools import Extension
from wheel.bdist_wheel import bdist_wheel as _bdist_wheel
from wheel_platform import get_wheel_platform_tag

try:
    from packaging import tags
    from packaging.version import Version
except ModuleNotFoundError:  # pragma: no cover
    try:
        from wheel.vendored.packaging import tags
        from wheel.vendored.packaging.version import Version
    except ImportError:  # pragma: no cover
        raise ImportError(
            "Neither 'packaging' nor 'wheel.vendored.packaging' is available. "
            "Please install the 'packaging' package."
        )

ROOT_DIR = os.path.dirname(__file__)


def get_version():
    """get version"""
    version = os.getenv("BUILD_VERSION", None)
    if version is None or len(version) == 0:
        return open(os.path.join(ROOT_DIR, "../../VERSION")).read().strip()
    return version


class SetupType(Enum):
    """setup type enum"""

    OPENYUANRONG = 1
    OPENYUANRONG_SDK = 2


class SetupSpec:
    """setup spec"""

    def __init__(self, setup_type: SetupType, name: str, description: str):
        self.setup_type = setup_type
        self.name = name
        self.description = description
        self.version = get_version()
        self.install_requires = []
        self.extras = {}
        self.entry_points = {}

    def get_packages(self):
        if self.setup_type == SetupType.OPENYUANRONG:
            return setuptools.find_packages(include=("yr.inner", "yr.inner.*"))
        if self.setup_type == SetupType.OPENYUANRONG_SDK:
            return setuptools.find_packages(
                exclude=("yr.tests", "yr.tests.*", "yr.inner", "yr.inner.*")
            )
        return []


setup_type_env = os.getenv("SETUP_TYPE", "")
base_name = os.getenv("YR_PACKAGE_NAME", "openyuanrong")

if setup_type_env == "sdk":
    setup_spec = SetupSpec(
        SetupType.OPENYUANRONG_SDK,
        f"{base_name}_sdk",
        "openyuanrong python sdk",
    )
    setup_spec.install_requires = [
        "cloudpickle==3.1.2",
        "msgpack==1.0.5",
        "protobuf==4.25.5",
        "cython==3.0.10",
        "pyyaml==6.0.2",
        "click==8.1.8",
        "requests==2.32.5",
        "websockets==15.0.1",
        "aiohttp>=3.9.0",   # tunnel_server Port B HTTP/WS server
        "httpx>=0.27.0",    # tunnel_client async HTTP forwarding
    ]
    setup_spec.entry_points = {
        "console_scripts": [
            "yrcli=yr.cli.scripts:main",
        ]
    }
else:
    setup_spec = SetupSpec(
        SetupType.OPENYUANRONG,
        base_name,
        "openyuanrong package",
    )
    setup_spec.install_requires = [
        f"{base_name}_sdk==" + setup_spec.version,
    ]
    setup_spec.extras["cpp"] = [f"{base_name}_cpp_sdk==" + setup_spec.version]
    setup_spec.entry_points = {
        "console_scripts": [
            "yr=yr.inner.scripts:run_yr",
        ]
    }



def copy_file(target, filename, root):
    """copy file"""
    if not os.path.exists(filename):
        return
    source = os.path.relpath(filename, root)
    dst = os.path.join(target, source)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        shutil.copy(filename, dst, follow_symlinks=True)
    except Exception as e:
        print(f"Warning: Failed to copy {filename}: {e}")


def contains_keyword(text, keywords):
    return any(kw in text for kw in keywords)


def is_shared_library(filename):
    return (
        filename.endswith((
            ".so",
            ".so.1",
            ".so.2",
            ".so.3",
            ".so.4",
            ".so.5",
            ".so.6",
            ".so.7",
            ".so.8",
            ".dylib",
        ))
        or ".so." in filename
        or ".dylib." in filename
    )


def select_fnruntime_binaries(candidates):
    ext_suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if ext_suffix:
        expected_name = f"fnruntime{ext_suffix}"
        matched = [path for path in candidates if os.path.basename(path) == expected_name]
        if matched:
            return matched
    fallback_names = {"fnruntime.so", "fnruntime.dylib"}
    fallback = [path for path in candidates if os.path.basename(path) in fallback_names]
    if fallback:
        return fallback[:1]
    if len(candidates) == 1:
        return candidates
    return []


def strip_nonmatching_fnruntime(target_dir):
    """remove fnruntime binaries that do not match current Python ABI"""
    yr_dir = os.path.join(target_dir, "yr")
    if not os.path.isdir(yr_dir):
        return
    candidates = []
    for name in os.listdir(yr_dir):
        if not name.startswith("fnruntime"):
            continue
        file_path = os.path.join(yr_dir, name)
        if os.path.isfile(file_path) and is_shared_library(name):
            candidates.append(file_path)
    keep = set(select_fnruntime_binaries(candidates))
    for filename in candidates:
        if filename not in keep:
            os.remove(filename)


def copy_openyuanrong(build_lib):
    """copy openyuanrong runtime files"""
    keyword_to_exclude = [
        "datasystem/sdk",
        "deploy/k8s",
        "functionsystem/bin/domain_scheduler",
        "functionsystem/bin/iam_server",
        "functionsystem/bin/runtime_manager",
        "functionsystem/sym",
        "pattern_faas/faasmanager",
        "runtime/sdk",
    ]
    file_to_exclude = [
        "faasfrontend",
        "faasfrontend.zip",
        "faasscheduler",
        "faasscheduler.zip",
    ]
    files_to_include = []
    root_dir = os.path.join(ROOT_DIR, "../../output/openyuanrong")
    for root, _, fs in os.walk(root_dir):
        if contains_keyword(root, keyword_to_exclude):
            continue
        for i in fs:
            if i in file_to_exclude:
                continue
            files_to_include.append(os.path.join(root, i))
    for filename in files_to_include:
        copy_file(os.path.join(build_lib, "yr/inner"), filename, root_dir)


def copy_openyuanrong_sdk(build_lib):
    """copy C++ SDK .so files"""
    cpp_sdk_root = os.path.abspath(os.path.join(ROOT_DIR, "../../build/output/runtime/sdk/cpp"))
    files_to_include = []
    for root, _, fs in os.walk(cpp_sdk_root):
        for i in fs:
            files_to_include.append(os.path.join(root, i))
    for filename in files_to_include:
        copy_file(os.path.join(build_lib, "yr/cpp"), filename, cpp_sdk_root)

    yr_root = os.path.join(ROOT_DIR, "yr")
    files_to_include = []
    fnruntime_candidates = []
    for root, _, fs in os.walk(yr_root):
        for i in fs:
            if not is_shared_library(i):
                continue
            file_path = os.path.join(root, i)
            if i.startswith("fnruntime"):
                fnruntime_candidates.append(file_path)
                continue
            files_to_include.append(file_path)
    files_to_include.extend(select_fnruntime_binaries(fnruntime_candidates))
    for filename in files_to_include:
        copy_file(build_lib, filename, ROOT_DIR)


def run_ext(build_lib):
    """run ext"""
    if setup_spec.setup_type == SetupType.OPENYUANRONG:
        copy_openyuanrong(build_lib)
    elif setup_spec.setup_type == SetupType.OPENYUANRONG_SDK:
        copy_openyuanrong_sdk(build_lib)


class BuildExtImpl(build_ext):
    """build ext impl"""

    def run(self):
        run_ext(self.build_lib)


class BuildPyImpl(build_py):
    """build py impl"""

    def run(self):
        super().run()
        strip_nonmatching_fnruntime(self.build_lib)
        shutil.rmtree(os.path.join(self.build_lib, "yr", "tests"), ignore_errors=True)


class BdistWheelImpl(_bdist_wheel):
    """bdist wheel impl"""

    def get_tag(self):
        """Build wheels with a supported platform tag."""
        tag = next(tags.sys_tags())
        platform_tag = get_wheel_platform_tag() or tag.platform
        return tag.interpreter, tag.abi, platform_tag

    def run(self):
        super().run()
        for wheel_name in os.listdir(self.dist_dir):
            if not wheel_name.endswith(".whl"):
                continue
            wheel_path = os.path.join(self.dist_dir, wheel_name)
            strip_wheel_tests(wheel_path)


class DevelopImpl(develop):
    """develop impl for editable install"""

    def run(self):
        super().run()
        run_ext(ROOT_DIR)


class BinaryDistribution(setuptools.Distribution):
    """binary distribution"""

    def __init__(self, attrs=None):
        super().__init__(attrs)
        # Keep generated metadata compatible with older upload validators.
        self.metadata.metadata_version = Version("2.2")

    def has_ext_modules(self):
        """has ext modules"""
        return True


def strip_wheel_tests(wheel_path):
    """remove yr/tests from built wheel"""
    temp_fd, temp_path = tempfile.mkstemp(suffix=".whl", dir=os.path.dirname(wheel_path))
    os.close(temp_fd)
    try:
        with zipfile.ZipFile(wheel_path, "r") as src, zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as dst:
            for member in src.infolist():
                if member.filename.startswith("yr/tests/"):
                    continue
                dst.writestr(member, src.read(member.filename))
        os.replace(temp_path, wheel_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


warnings.filterwarnings("ignore", category=setuptools.SetuptoolsDeprecationWarning)

# 添加一个虚拟扩展模块来触发 build_ext
ext_modules = []
if setup_spec.setup_type == SetupType.OPENYUANRONG:
    # 虚拟扩展模块，不实际编译，仅用于触发 build_ext
    ext_modules = [Extension("yr._dummy", sources=[])]

setuptools.setup(
    name=setup_spec.name,
    version=setup_spec.version,
    author="openyuanrong",
    python_requires=">=3.9,<3.13",
    classifiers=[
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    cmdclass={
        "bdist_wheel": BdistWheelImpl,
        "build_ext": BuildExtImpl,
        "build_py": BuildPyImpl,
        "develop": DevelopImpl,
    },
    distclass=BinaryDistribution,
    ext_modules=ext_modules,
    packages=setup_spec.get_packages(),
    install_requires=setup_spec.install_requires,
    include_package_data=False,
    package_data={
        "yr": ["includes/*.pxd", "includes/*.pxi", "*.so.*", "*.so", "*.dylib.*", "*.dylib"],
    },
    exclude_package_data={
        "": ["BUILD", "BUILD.bazel"],
        "yr": ["tests/*", "tests/**/*"],
    },
    extras_require=setup_spec.extras,
    entry_points=setup_spec.entry_points,
)
