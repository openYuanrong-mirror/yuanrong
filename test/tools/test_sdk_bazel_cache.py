#!/usr/bin/env python3

"""Regression contracts for SDK Bazel cache reuse and Jenkins compatibility."""

import os
import pathlib
import subprocess
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class SdkBazelCacheTest(unittest.TestCase):
    def test_python_abi_does_not_invalidate_common_bazel_actions(self):
        build_script = (REPO_ROOT / "build.sh").read_text(encoding="utf-8")
        bazelrc = (REPO_ROOT / ".bazelrc").read_text(encoding="utf-8")
        python_build = (REPO_ROOT / "api/python/BUILD.bazel").read_text(encoding="utf-8")

        self.assertNotIn("--action_env=PYTHON3_BIN_PATH", build_script)
        self.assertNotIn("--action_env=PYTHON3_BIN_PATH", bazelrc)
        self.assertIn("--repo_env=PYTHON3_BIN_PATH=${PYTHON_BIN_FULL_PATH}", build_script)

        package_start = python_build.index('name = "yr_python_pkg"')
        package_end = python_build.index('name = "libruntime_proto_py"', package_start)
        self.assertNotIn("PYTHON3_BIN_PATH", python_build[package_start:package_end])
        self.assertIn("python ABI extension is staged by build.sh", python_build)
        self.assertNotIn("sync_libruntime_proto_workspace", python_build)
        self.assertIn("stage_python_bazel_outputs", build_script)

    def test_sdk_modes_preserve_the_legacy_jenkins_path(self):
        build_script = (REPO_ROOT / "build.sh").read_text(encoding="utf-8")
        sdk_script = (
            REPO_ROOT / ".buildkite/build_openyuanrong_sdk_wheels.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'BAZEL_TARGETS="//api/cpp:yr_cpp_pkg //api/java:yr_java_pkg '
            '//api/python:yr_python_pkg //api/go:yr_go_pkg //api/rust:yr_rust_pkg"',
            build_script,
        )
        self.assertIn('BUILD_SDK_COMMON_ONLY="${BUILD_SDK_COMMON_ONLY:-0}"', build_script)
        self.assertIn('BUILD_SDK_WHEEL_ONLY="${BUILD_SDK_WHEEL_ONLY:-0}"', build_script)
        self.assertIn('SDK_COMMON_BAZEL_TARGETS="//api/cpp:cpp_strip"', build_script)
        self.assertIn(
            'SDK_WHEEL_BAZEL_TARGETS="//api/cpp:yr_cpp_pkg //api/python:yr_python_pkg"',
            build_script,
        )
        self.assertIn("BUILD_SDK_COMMON_ONLY=1", sdk_script)
        self.assertIn("BUILD_SDK_WHEEL_ONLY=1", sdk_script)
        self.assertIn('SDK_BUILD_MODE="${SDK_BUILD_MODE:-wheel}"', sdk_script)

        # Jenkins still invokes the default mode with the existing -P/-p interface.
        self.assertIn('P)\n\t\tPACKAGE_ALL="true"', build_script)
        self.assertIn('p)\n\t\tif [[ "${OPTARG}" == "multi" ]]', build_script)
        self.assertIn('name = "yr_python_pkg"', (REPO_ROOT / "api/python/BUILD.bazel").read_text())

    def test_macos_sdk_uses_persistent_local_caches(self):
        pipeline = (REPO_ROOT / ".buildkite/pipeline.dynamic.yml").read_text(
            encoding="utf-8"
        )
        sdk_script = (
            REPO_ROOT / ".buildkite/build_openyuanrong_sdk_wheels.sh"
        ).read_text(encoding="utf-8")
        cache_script = (
            REPO_ROOT / ".buildkite/configure_macos_local_cache.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('SDK_BAZEL_DISK_CACHE="${_YR_MACOS_CACHE_ROOT}', cache_script)
        self.assertIn('BUILDKITE_BUILD_PATH:-}', cache_script)
        self.assertIn('cache_args=(-l "${SDK_BAZEL_DISK_CACHE}")', sdk_script)

        with tempfile.TemporaryDirectory() as cache_root:
            env = os.environ.copy()
            env["YR_MACOS_CACHE_ROOT"] = cache_root
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    (
                        '. "$1"; '
                        'printf "%s\\n%s\\n%s\\n" '
                        '"$SDK_BAZEL_DISK_CACHE" '
                        '"$BAZEL_REPOSITORY_CACHE" '
                        '"$PIP_CACHE_DIR"'
                    ),
                    "bash",
                    str(REPO_ROOT / ".buildkite/configure_macos_local_cache.sh"),
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            cache_paths = result.stdout.splitlines()[-3:]
            self.assertEqual(len(cache_paths), 3)
            for cache_path in cache_paths:
                self.assertTrue(pathlib.Path(cache_path).is_dir())
                self.assertTrue(
                    pathlib.Path(cache_path).is_relative_to(cache_root)
                )



if __name__ == "__main__":
    unittest.main()
