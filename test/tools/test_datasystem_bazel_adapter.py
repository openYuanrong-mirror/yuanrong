#!/usr/bin/env python3
# coding=UTF-8

"""Regression tests for the DataSystem source-build Bazel adapter."""

import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DATASYSTEM_ROOT = REPO_ROOT / "datasystem"
ADAPTER = REPO_ROOT / "bazel" / "datasystem_build.bzl"
DEPENDENCIES = REPO_ROOT / "bazel" / "datasystem_deps.bzl"


class DataSystemBazelAdapterTest(unittest.TestCase):
    @staticmethod
    def _target_block(adapter, target_name):
        name_position = adapter.index(f'name = "{target_name}"')
        block_start = adapter.rfind("cc_library(", 0, name_position)
        block_end = adapter.index("\n)\n", name_position)
        return adapter[block_start:block_end]

    def test_literal_datasystem_source_paths_exist(self):
        """The adapter must not reference files removed from the pinned submodule."""
        adapter = ADAPTER.read_text(encoding="utf-8")
        source_paths = sorted(
            set(
                re.findall(
                    r'"((?:src|include|python)/[^"*{}\[\]]+)"',
                    adapter,
                )
            )
        )

        missing_paths = [
            source_path
            for source_path in source_paths
            if not (DATASYSTEM_ROOT / source_path).exists()
        ]

        self.assertEqual([], missing_paths)

    def test_brpc_compatibility_files_are_owned_by_superproject(self):
        """Master-side BRPC deps must not rely on files absent from the sandbox gitlink."""
        dependencies = DEPENDENCIES.read_text(encoding="utf-8")
        adapter = ADAPTER.read_text(encoding="utf-8")
        expected_labels = (
            "@//bazel/datasystem:leveldb.BUILD",
            "@//bazel/patches:brpc_avoid_glog_flag_conflicts.patch",
            "@//bazel/patches:brpc_fix_boringssl_compat.patch",
        )

        for label in expected_labels:
            self.assertIn(label, dependencies)
        self.assertNotIn("third_party/patches/brpc/", adapter)
        self.assertNotIn("third_party/leveldb.BUILD", adapter)

    def test_common_buffer_declares_generated_brpc_headers(self):
        """Sandboxed buffer compilation must see RPC headers included by client headers."""
        adapter = ADAPTER.read_text(encoding="utf-8")
        common_buffer = self._target_block(adapter, "common_buffer")

        for dependency in (
            ":master_object_brpc",
            ":object_posix_brpc",
            ":worker_object_brpc",
        ):
            self.assertIn(f'"{dependency}"', common_buffer)

    def test_client_library_excludes_retired_sources(self):
        """The adapter must not compile orphan sources omitted by DataSystem targets."""
        adapter = ADAPTER.read_text(encoding="utf-8")
        client_library = self._target_block(adapter, "datasystem_client_lib")

        self.assertIn(
            '"src/datasystem/client/transport/rpc/client_request_auth.cpp"',
            client_library,
        )

    def test_brpc_factory_implementation_is_linked(self):
        """Client and stub-cache targets must link the split BRPC factory target."""
        adapter = ADAPTER.read_text(encoding="utf-8")
        brpc_factory = self._target_block(adapter, "brpc_factory")

        self.assertIn(
            '"src/datasystem/common/rpc/brpc_factory.cpp"',
            brpc_factory,
        )
        for target_name in ("rpc_stub_cache_mgr", "datasystem_client_lib"):
            target = self._target_block(adapter, target_name)
            self.assertIn('":brpc_factory"', target)


if __name__ == "__main__":
    unittest.main()
