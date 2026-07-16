#!/usr/bin/env python3

"""Regression tests for Buildkite main-build artifact reuse."""

import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / ".buildkite" / "pipeline.dynamic.yml"


class BuildkiteMainPackagingTest(unittest.TestCase):
    def test_main_builds_reuse_make_all_release_artifacts(self):
        pipeline = PIPELINE.read_text(encoding="utf-8")

        self.assertEqual(pipeline.count('make all BUILD_VERSION='), 2)
        self.assertNotIn("Repackage release artifacts", pipeline)
        self.assertNotIn("bash scripts/package_yuanrong.sh", pipeline)
        self.assertNotIn("python3 setup.py bdist_wheel", pipeline)

        self.assertEqual(pipeline.count("cp datasystem/output/*.whl output/"), 2)
        self.assertEqual(pipeline.count("cp functionsystem/output/*.whl output/"), 2)
        self.assertEqual(pipeline.count("for required_wheel in"), 2)
        self.assertEqual(pipeline.count("Verify Go plugin ABI"), 2)


if __name__ == "__main__":
    unittest.main()
