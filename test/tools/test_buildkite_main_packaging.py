#!/usr/bin/env python3

"""Regression tests for Buildkite main-build artifact reuse."""

import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / ".buildkite" / "pipeline.dynamic.yml"
BUILD_SCRIPT = REPO_ROOT / "build.sh"


class BuildkiteMainPackagingTest(unittest.TestCase):
    def test_main_builds_reuse_make_all_release_artifacts(self):
        pipeline = PIPELINE.read_text(encoding="utf-8")

        self.assertEqual(pipeline.count('make all BUILD_VERSION='), 2)
        self.assertNotIn("Repackage release artifacts", pipeline)
        self.assertNotIn("bash scripts/package_yuanrong.sh", pipeline)
        self.assertEqual(
            pipeline.count("api/python-rrt && RRT_RUNTIME_SRC="),
            pipeline.count("python3 setup.py bdist_wheel"),
        )

        self.assertEqual(pipeline.count("cp datasystem/output/*.whl output/"), 2)
        self.assertEqual(pipeline.count("cp functionsystem/output/*.whl output/"), 2)
        self.assertEqual(pipeline.count("for required_wheel in"), 2)
        self.assertEqual(pipeline.count("Verify Go plugin ABI"), 2)

    def test_validation_package_version_does_not_invalidate_all_bazel_actions(self):
        pipeline = PIPELINE.read_text(encoding="utf-8")
        build_script = BUILD_SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            'BAZEL_BUILD_VERSION="${BAZEL_BUILD_VERSION:-${BUILD_VERSION}}"',
            build_script,
        )
        self.assertIn(
            "--action_env=BUILD_VERSION=${BAZEL_BUILD_VERSION}",
            build_script,
        )
        self.assertNotIn(
            "--action_env=BUILD_VERSION=${BUILD_VERSION}",
            build_script,
        )

        stable_version = (
            r'BAZEL_BUILD_VERSION="\$\${BAZEL_BUILD_VERSION:-'
            r'\$\${TAG_BUILD_VERSION:-\$\$(cat VERSION)}}"'
        )
        self.assertEqual(
            pipeline.count(stable_version),
            pipeline.count('YR_BUILD_VERSION="'),
        )


if __name__ == "__main__":
    unittest.main()
