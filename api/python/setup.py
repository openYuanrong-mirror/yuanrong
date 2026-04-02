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
import tempfile
import warnings
import zipfile

import setuptools
from packaging import tags
from setuptools.command.build_ext import build_ext
from setuptools.command.build_py import build_py
from setuptools.command.develop import develop
from setuptools import Extension
from wheel.bdist_wheel import bdist_wheel as _bdist_wheel

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
    OPENYUANRONG_RUNTIME = 2
    OPENYUANRONG_SERVICE = 3


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
            return setuptools.find_packages(
                exclude=(
                    "yr.tests",
                    "yr.tests.*",
                ),
            )
        if self.setup_type == SetupType.OPENYUANRONG_RUNTIME:
            return setuptools.find_packages(
                include=("yr", "yr.inner", "yr.inner.*"),
            )
        if self.setup_type == SetupType.OPENYUANRONG_SERVICE:
            return setuptools.find_packages(
                include=("yr", "yr.inner", "yr.inner.*"),
            )
        return []


setup_type_env = os.getenv("SETUP_TYPE", "")

if setup_type_env == "runtime":
    setup_spec = SetupSpec(
        SetupType.OPENYUANRONG_RUNTIME,
        "openyuanrong_runtime",
        "openyuanrong runtime package",
    )
    setup_spec.install_requires = ["openyuanrong==" + setup_spec.version]
elif setup_type_env == "service":
    setup_spec = SetupSpec(
        SetupType.OPENYUANRONG_SERVICE,
        "openyuanrong_service",
        "openyuanrong service package",
    )
    setup_spec.install_requires = ["openyuanrong==" + setup_spec.version]
else:
    setup_spec = SetupSpec(
        SetupType.OPENYUANRONG,
        "openyuanrong",
        "openyuanrong - serverless computing framework",
    )
    setup_spec.install_requires = [
        "cloudpickle==2.2.1",
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
    setup_spec.extras["runtime"] = ["openyuanrong_runtime==" + setup_spec.version]
    setup_spec.extras["service"] = ["openyuanrong_service==" + setup_spec.version]
    setup_spec.extras["all"] = [
        "openyuanrong_runtime==" + setup_spec.version,
        "openyuanrong_service==" + setup_spec.version,
    ]
    setup_spec.entry_points = {
        "console_scripts": [
            "yr=yr.inner.scripts:run_yr",
            "yrcli=yr.cli.scripts:main",
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


def copy_openyuanrong_runtime(build_lib):
    """copy runtime components"""
    root_dir = os.path.join(ROOT_DIR, "../../output/openyuanrong")
    runtime_dir = os.path.join(root_dir, "runtime")

    # Copy Go runtime
    go_dir = os.path.join(runtime_dir, "service/go/bin")
    if os.path.exists(go_dir):
        for f in os.listdir(go_dir):
            src = os.path.join(go_dir, f)
            dst = os.path.join(build_lib, "yr/runtime/service/go/bin", f)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.isfile(src):
                shutil.copy(src, dst, follow_symlinks=True)

    # Copy Java runtime
    java_dir = os.path.join(runtime_dir, "service/java")
    if os.path.exists(java_dir):
        for root, dirs, files in os.walk(java_dir):
            for f in files:
                src = os.path.join(root, f)
                rel_path = os.path.relpath(src, java_dir)
                dst = os.path.join(build_lib, "yr/runtime/service/java", rel_path)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy(src, dst, follow_symlinks=True)


def copy_openyuanrong_cpp_sdk(build_lib):
    """copy C++ SDK payload"""
    root_dir = os.path.join(ROOT_DIR, "../../output/openyuanrong")

    # Copy C++ SDK headers and libraries
    cpp_sdk_dir = os.path.join(root_dir, "runtime/sdk/cpp")
    if os.path.exists(cpp_sdk_dir):
        for root, dirs, files in os.walk(cpp_sdk_dir):
            for f in files:
                src = os.path.join(root, f)
                rel_path = os.path.relpath(src, cpp_sdk_dir)
                dst = os.path.join(build_lib, "yr/cpp", rel_path)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy(src, dst, follow_symlinks=True)

    # Copy C++ service runtime
    cpp_service_dir = os.path.join(root_dir, "runtime/service/cpp")
    if os.path.exists(cpp_service_dir):
        for root, dirs, files in os.walk(cpp_service_dir):
            for f in files:
                src = os.path.join(root, f)
                rel_path = os.path.relpath(src, cpp_service_dir)
                dst = os.path.join(build_lib, "yr/runtime/service/cpp", rel_path)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy(src, dst, follow_symlinks=True)


def copy_openyuanrong_services(build_lib):
    """copy dashboard and faas payload"""
    root_dir = os.path.join(ROOT_DIR, "../../output/openyuanrong")

    # Copy Dashboard
    dashboard_dir = os.path.join(root_dir, "dashboard")
    if os.path.exists(dashboard_dir):
        for root, dirs, files in os.walk(dashboard_dir):
            for f in files:
                src = os.path.join(root, f)
                rel_path = os.path.relpath(src, dashboard_dir)
                dst = os.path.join(build_lib, "yr/dashboard", rel_path)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy(src, dst, follow_symlinks=True)

    # Copy FaaS (exclude .zip files and standalone binaries to reduce package size)
    faas_dir = os.path.join(root_dir, "pattern/pattern_faas")
    if os.path.exists(faas_dir):
        for root, dirs, files in os.walk(faas_dir):
            if contains_keyword(root, ["faasmanager"]):
                continue
            for f in files:
                # Skip .zip files and standalone binaries (keep only .so shared libraries)
                # .so files are used by Python/Go/Java runtimes via ctypes/cgo
                if f.endswith('.zip') or (f in ['faasfrontend', 'faasscheduler']):
                    continue
                src = os.path.join(root, f)
                rel_path = os.path.relpath(src, faas_dir)
                dst = os.path.join(build_lib, "yr/faas", rel_path)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy(src, dst, follow_symlinks=True)


def copy_openyuanrong(build_lib):
    """copy openyuanrong"""

    files_to_include = []
    for root, _, fs in os.walk("./yr"):
        for i in fs:
            if i.endswith((".so", ".so.1", ".so.2", ".so.3", ".so.4", ".so.5", ".so.6", ".so.7", ".so.8",
                           ".dylib")) or ".so." in i or ".dylib." in i:
                files_to_include.append(os.path.join(root, i))
    for filename in files_to_include:
        copy_file(build_lib, filename, ROOT_DIR)


def run_ext(build_lib):
    """run ext"""
    if setup_spec.setup_type == SetupType.OPENYUANRONG:
        copy_openyuanrong(build_lib)
        return
    if setup_spec.setup_type == SetupType.OPENYUANRONG_RUNTIME:
        copy_openyuanrong_runtime(build_lib)
        copy_openyuanrong_cpp_sdk(build_lib)
        return
    if setup_spec.setup_type == SetupType.OPENYUANRONG_SERVICE:
        copy_openyuanrong_services(build_lib)


class BuildExtImpl(build_ext):
    """build ext impl"""

    def run(self):
        run_ext(self.build_lib)


class BuildPyImpl(build_py):
    """build py impl"""

    def run(self):
        super().run()
        shutil.rmtree(os.path.join(self.build_lib, "yr", "tests"), ignore_errors=True)


class BdistWheelImpl(_bdist_wheel):
    """bdist wheel impl"""

    def get_tag(self):
        """Build wheels with a supported platform tag."""
        tag = next(tags.sys_tags())
        return tag.interpreter, tag.abi, tag.platform

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
if setup_spec.setup_type in [
    SetupType.OPENYUANRONG,
    SetupType.OPENYUANRONG_RUNTIME,
    SetupType.OPENYUANRONG_SERVICE,
]:
    # 虚拟扩展模块，不实际编译，仅用于触发 build_ext
    ext_modules = [Extension("yr._dummy", sources=[])]

setuptools.setup(
    name=setup_spec.name,
    version=setup_spec.version,
    author="openyuanrong",
    python_requires=">=3.9,<3.12",
    classifiers=[
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
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
