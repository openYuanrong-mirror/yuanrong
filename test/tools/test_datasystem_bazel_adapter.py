#!/usr/bin/env python3
# coding=UTF-8

"""Regression tests for the DataSystem source-build Bazel adapter."""

import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DATASYSTEM_ROOT = REPO_ROOT / "datasystem"
ADAPTER = REPO_ROOT / "bazel" / "datasystem_build.bzl"


class DataSystemBazelAdapterTest(unittest.TestCase):
    @staticmethod
    def _target_block(adapter, target_name):
        block_start = adapter.index(
            f'cc_library(\n    name = "{target_name}"'
        )
        name_position = adapter.index(f'name = "{target_name}"', block_start)
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

    def test_cluster_topology_links_diagnostics_implementation(self):
        """Topology users must link the implementation for diagnostic helpers."""
        adapter = ADAPTER.read_text(encoding="utf-8")
        cluster_topology = self._target_block(adapter, "cluster_topology")

        self.assertIn(
            '"src/datasystem/cluster/model/topology_diagnostics.cpp"',
            cluster_topology,
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

    def test_common_rpc_zmq_client_links_api_deadline_helpers(self):
        """RPC client users must link the split API deadline helpers."""
        adapter = ADAPTER.read_text(encoding="utf-8")
        common_rpc_zmq_client = self._target_block(
            adapter, "common_rpc_zmq_client"
        )

        self.assertIn(
            '"src/datasystem/common/rpc/api_deadline_helpers.cpp"',
            common_rpc_zmq_client,
        )


if __name__ == "__main__":
    unittest.main()
