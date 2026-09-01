#!/usr/bin/env python3
# coding=UTF-8

"""Regression tests for Sandbox SDK packaging in the root Makefile."""

import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"


class MakefileSandboxSDKTest(unittest.TestCase):
    def test_sandbox_sdk_receives_parent_build_version(self):
        makefile = MAKEFILE.read_text(encoding="utf-8")

        self.assertIn(
            'BUILD_VERSION="$(BUILD_VERSION)" $(LOCAL_CACHE_RUN) '
            'bash sandbox-sdk/build.sh',
            makefile,
        )


if __name__ == "__main__":
    unittest.main()
