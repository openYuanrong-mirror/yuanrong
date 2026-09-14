#!/usr/bin/env python3

"""Regression tests for Buildkite main-build artifact reuse."""

import os
import pathlib
import subprocess
import unittest

import yaml


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / ".buildkite" / "pipeline.dynamic.yml"
CACHE_CONFIG_SCRIPT = REPO_ROOT / ".buildkite" / "configure_bazel_remote_cache.sh"
BUILD_SCRIPT = REPO_ROOT / "build.sh"
BAZELRC = REPO_ROOT / ".bazelrc"
CPP_BUILD = REPO_ROOT / "api" / "cpp" / "BUILD.bazel"
JAVA_BUILD = REPO_ROOT / "api" / "java" / "BUILD.bazel"
COMPILE_IMAGE = REPO_ROOT / "ci" / "ubuntu" / "Dockerfile.ubuntu2004"


class BuildkiteMainPackagingTest(unittest.TestCase):
    def test_pipeline_artifact_dependencies_are_complete(self):
        cases = [
            ({}, 12),
            ({"ENABLE_LINUX_ARM": "false"}, 7),
            ({"ENABLE_SANDBOX_PACKAGE": "false"}, 6),
            ({"ENABLE_RRT_ONLY": "true"}, 2),
            ({"ENABLE_SANDBOX_K8S_TEST_ONLY": "true"}, 1),
            ({"ENABLE_SANDBOX_MANIFEST": "false"}, 10),
        ]
        for overrides, expected_count in cases:
            with self.subTest(overrides=overrides):
                env = {k: v for k, v in os.environ.items()
                       if not k.startswith(("ENABLE_", "SDK_", "PUBLISH_"))}
                env.update(overrides)
                result = subprocess.run(["bash", str(PIPELINE)], cwd=REPO_ROOT,
                                        env=env, check=True, capture_output=True, text=True)
                steps = yaml.safe_load(result.stdout)["steps"]
                keys = {step["key"] for step in steps}
                self.assertEqual(len(steps), expected_count)
                self.assertEqual(len(keys), len(steps))
                self.assertFalse(any(key.startswith(("build-sdk-", "publish-runtime-")) for key in keys))
                for step in steps:
                    dependencies = step.get("depends_on", [])
                    if isinstance(dependencies, str):
                        dependencies = [dependencies]
                    self.assertTrue(set(dependencies) <= keys, (step["key"], dependencies, keys))
                    if step["key"].startswith("build-all-"):
                        self.assertIn("export BUILD_PYTHON_SDK_WHEEL=0", step["command"])
                if not overrides:
                    self.assertTrue({"test-k8s", "test-sandbox-sdk", "build-data-plane-gateway-amd64", "build-rrt-amd64"} <= keys)

    def test_core_wheel_is_only_wired_into_buildkite(self):
        def tracked_references(needle):
            result = subprocess.run(
                [
                    "git",
                    "grep",
                    "-l",
                    "-F",
                    needle,
                    "--",
                    ".",
                    ":(exclude)test/**",
                    ":(exclude).buildkite/package_core_wheel.py",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode not in (0, 1):
                result.check_returncode()
            return result.stdout.splitlines()

        self.assertEqual(
            tracked_references(".buildkite/package_core_wheel.py"),
            [".buildkite/pipeline.dynamic.yml"],
        )
        self.assertEqual(
            tracked_references("scripts/trim.sh"),
            [],
        )

    def test_linux_bazel_remote_cache_is_enabled_by_default(self):
        pipeline = PIPELINE.read_text(encoding="utf-8")
        cache_config = CACHE_CONFIG_SCRIPT.read_text(encoding="utf-8")

        self.assertGreaterEqual(
            pipeline.count(". .buildkite/configure_bazel_remote_cache.sh"),
            2,
        )
        self.assertIn(
            "YR_BUILDKITE_ENABLE_BAZEL_REMOTE_CACHE:-true",
            cache_config,
        )
        self.assertNotIn(
            "YR_BUILDKITE_ENABLE_BAZEL_REMOTE_CACHE:-false",
            cache_config,
        )

    def test_python314_builder_installs_obs_sdk_for_every_python(self):
        pipeline = PIPELINE.read_text(encoding="utf-8")
        dockerfile = COMPILE_IMAGE.read_text(encoding="utf-8")

        self.assertIn("for v in 3.9 3.10 3.11 3.12 3.13 3.14", dockerfile)
        self.assertIn(
            "--break-system-packages setuptools wheel packaging esdk-obs-python",
            dockerfile,
        )
        self.assertIn(
            "compile-ubuntu2004:v20260717_py3146_obs",
            pipeline,
        )

    def test_main_builds_reuse_make_all_release_artifacts(self):
        pipeline = PIPELINE.read_text(encoding="utf-8")

        self.assertEqual(pipeline.count('make all BUILD_VERSION='), 2)
        self.assertNotIn("Repackage release artifacts", pipeline)
        self.assertNotIn("bash scripts/package_yuanrong.sh", pipeline)
        self.assertNotIn(
            "SETUP_TYPE= PYTHON_RUNTIME_VERSION=python3.11 "
            "python3 setup.py bdist_wheel",
            pipeline,
        )
        self.assertEqual(
            pipeline.count("api/python-rrt && RRT_RUNTIME_SRC="),
            pipeline.count("python3 setup.py bdist_wheel"),
        )

        self.assertNotIn("cp datasystem/output/*.whl output/", pipeline)
        self.assertNotIn("cp functionsystem/output/*.whl output/", pipeline)
        self.assertEqual(
            pipeline.count("find output -maxdepth 1 -name 'openyuanrong-*.tar.gz'"),
            2,
        )
        self.assertEqual(
            pipeline.count("find output -maxdepth 1 -name 'openyuanrong-*.whl'"),
            2,
        )
        self.assertEqual(
            pipeline.count("python3 .buildkite/package_core_wheel.py"),
            2,
        )
        self.assertEqual(
            pipeline.count(
                "find artifacts/release -maxdepth 1 "
                "-name 'openyuanrong_core-*.whl'"
            ),
            2,
        )
        self.assertNotIn(
            "package_core_release.sh",
            pipeline,
        )
        self.assertNotIn("*-core.tar.gz", pipeline)
        self.assertEqual(pipeline.count("Verify Go plugin ABI"), 2)

    def test_validation_package_version_does_not_invalidate_all_bazel_actions(self):
        pipeline = PIPELINE.read_text(encoding="utf-8")
        build_script = BUILD_SCRIPT.read_text(encoding="utf-8")
        bazelrc = BAZELRC.read_text(encoding="utf-8")
        cpp_build = CPP_BUILD.read_text(encoding="utf-8")
        java_build = JAVA_BUILD.read_text(encoding="utf-8")

        self.assertIn(
            'BAZEL_BUILD_VERSION="${BAZEL_BUILD_VERSION:-${BUILD_VERSION}}"',
            build_script,
        )
        self.assertIn(
            "--define=BUILD_VERSION=${BAZEL_BUILD_VERSION}",
            build_script,
        )
        self.assertNotIn(
            "--action_env=BUILD_VERSION=${BAZEL_BUILD_VERSION}",
            build_script,
        )
        self.assertNotIn("--action_env=BUILD_VERSION", bazelrc)
        self.assertIn("build --define=BUILD_VERSION=v0.7.0", bazelrc)
        self.assertIn("BUILD_VERSION", cpp_build)
        self.assertIn("$(BUILD_VERSION)", cpp_build)
        self.assertGreaterEqual(java_build.count("$(BUILD_VERSION)"), 2)

        stable_version = (
            r'BAZEL_BUILD_VERSION="\$\${BAZEL_BUILD_VERSION:-'
            r'\$\${TAG_BUILD_VERSION:-\$\$(cat VERSION)}}"'
        )
        self.assertEqual(
            pipeline.count(stable_version) + 1,
            pipeline.count('YR_BUILD_VERSION="'),
        )


if __name__ == "__main__":
    unittest.main()
