#!/usr/bin/env python3
# coding=UTF-8

"""Regression checks for failures seen in the macOS SDK build matrix."""

import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEDULER_MANAGER = REPO_ROOT / "src/libruntime/invokeadaptor/scheduler_manager.cpp"
DOWNLOAD_DEPENDENCY = REPO_ROOT / "tools/download_dependency.sh"


class MacosBuildRegressionTest(unittest.TestCase):
    def test_scheduler_reset_iterates_by_const_reference(self):
        source = SCHEDULER_MANAGER.read_text(encoding="utf-8")

        self.assertIn("for (const auto &info : schedulerInfoList)", source)
        self.assertNotIn("for (const auto info : schedulerInfoList)", source)

    def test_runtime_dependency_cache_detects_darwin_locally(self):
        script = DOWNLOAD_DEPENDENCY.read_text(encoding="utf-8")

        self.assertIn('[[ "$(uname -s)" == "Darwin" ]]', script)
        self.assertNotIn('[ "$IS_MACOS" == "true" ]', script)


if __name__ == "__main__":
    unittest.main()
