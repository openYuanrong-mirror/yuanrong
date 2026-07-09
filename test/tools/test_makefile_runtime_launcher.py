#!/usr/bin/env python3
# coding=UTF-8

"""Regression tests for runtime-launcher build entrypoints in the root Makefile."""

import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"


class MakefileRuntimeLauncherTest(unittest.TestCase):
    def test_runtime_launcher_target_delegates_to_functionsystem_executor(self):
        makefile = MAKEFILE.read_text(encoding="utf-8")

        self.assertIn("bash run.sh build --component runtime_launcher", makefile)
        self.assertIn("cp functionsystem/runtime-launcher/bin/runtime/runtime-launcher output/runtime-launcher", makefile)
        self.assertNotIn("cd functionsystem/runtime-launcher &&", makefile)

    def test_make_all_does_not_duplicate_runtime_launcher_target(self):
        makefile = MAKEFILE.read_text(encoding="utf-8")
        all_target = re.search(r"^all:\s*(.*)$", makefile, re.MULTILINE)

        self.assertIsNotNone(all_target)
        self.assertNotIn("runtime_launcher", all_target.group(1).split())
        self.assertIn("functionsystem", all_target.group(1).split())


if __name__ == "__main__":
    unittest.main()
