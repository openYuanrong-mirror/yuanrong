#!/usr/bin/env python3

"""Regression checks for the DataSystem source SDK Bazel ownership boundary."""

import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE = REPO_ROOT / "WORKSPACE"
LEGACY_DATASYSTEM_BUILD = REPO_ROOT / "bazel" / "datasystem_build.bzl"
LEGACY_DATASYSTEM_DEPS = REPO_ROOT / "bazel" / "datasystem_deps.bzl"
LEGACY_DATASYSTEM_RECIPES = REPO_ROOT / "bazel" / "datasystem"
LEGACY_PLATFORM_REPOSITORY = REPO_ROOT / "bazel" / "platform_local_repository.bzl"
LEGACY_DATASYSTEM_DEPENDENCY_LOADER = REPO_ROOT / "bazel" / "maybe_datasystem_deps.bzl"
LEGACY_DATASYSTEM_STUB = REPO_ROOT / "bazel" / "stub_datasystem.bzl"
LEGACY_DATASYSTEM_RULES = REPO_ROOT / "bazel" / "datasystem_rules.bzl"
DATASYSTEM_SDK_BUILD = REPO_ROOT / "datasystem" / "bazel" / "sdk" / "BUILD.bazel"
DATASYSTEM_SDK_DEPS = REPO_ROOT / "datasystem" / "bazel" / "sdk" / "deps.bzl"
DATASYSTEM_SDK_ROOT_BUILD = REPO_ROOT / "datasystem" / "bazel" / "sdk" / "root.BUILD.bazel"
DATASYSTEM_SDK_WORKSPACE = REPO_ROOT / "datasystem" / "bazel" / "sdk" / "workspace.bzl"
PRELOAD_GRPC = REPO_ROOT / "bazel" / "preload_grpc.bzl"
GRPC_EXTERNAL_REPO_PATCH = REPO_ROOT / "patch" / "grpc_1_65_4_external_repo.patch"


class DataSystemSdkBuildContractTest(unittest.TestCase):
    def test_yuanrong_uses_datasystem_owned_source_build(self):
        workspace = WORKSPACE.read_text(encoding="utf-8")

        self.assertNotIn('build_file = "@//bazel:datasystem_build.bzl"', workspace)
        self.assertIn('name = "datasystem_sdk_config"', workspace)
        self.assertIn('path = "datasystem"', workspace)
        self.assertIn(
            'load("@datasystem_sdk_config//bazel/sdk:workspace.bzl", "datasystem_source_sdk")',
            workspace,
        )
        self.assertIn("datasystem_source_sdk(", workspace)
        self.assertIn('name = "datasystem_sdk"', workspace)
        self.assertIn("enabled = not IS_MACOS", workspace)
        self.assertFalse(LEGACY_DATASYSTEM_BUILD.exists())

    def test_datasystem_exposes_stable_source_sdk_targets(self):
        sdk_build = DATASYSTEM_SDK_BUILD.read_text(encoding="utf-8")

        for target in ("client", "headers", "runtime_files"):
            self.assertIn(f'name = "{target}"', sdk_build)
        self.assertIn('"//src/datasystem/client:datasystem"', sdk_build)
        self.assertIn('name = "runtime_files"', sdk_build)
        self.assertNotIn('name = "shared"', sdk_build)

        root_build = DATASYSTEM_SDK_ROOT_BUILD.read_text(encoding="utf-8")
        for target in ("enable_pipeline_h2d", "enable_urma", "with_tests"):
            self.assertIn(f'name = "{target}"', root_build)
        self.assertNotIn("cc_shared_library", root_build)

        sdk_deps = DATASYSTEM_SDK_DEPS.read_text(encoding="utf-8")
        self.assertIn('def source_sdk_deps(datasystem_repository = "datasystem_sdk"):', sdk_deps)
        self.assertIn('maybe(ascend_configure, name = "local_ascend")', sdk_deps)
        self.assertIn('maybe(cuda_local_repository, name = "local_cuda")', sdk_deps)
        self.assertNotIn("datasystem_sdk_protobuf", sdk_deps)
        self.assertNotIn('name = "ds_grpc"', sdk_deps)

        workspace = WORKSPACE.read_text(encoding="utf-8")
        self.assertNotIn('"@com_google_protobuf": "@datasystem_sdk_protobuf"', workspace)
        self.assertNotIn('"@com_github_grpc_grpc": "@ds_grpc"', workspace)

    def test_host_grpc_codegen_supports_external_proto_repositories(self):
        preload_grpc = PRELOAD_GRPC.read_text(encoding="utf-8")
        patch = GRPC_EXTERNAL_REPO_PATCH.read_text(encoding="utf-8")

        self.assertIn('"@//patch:grpc_1_65_4_external_repo.patch"', preload_grpc)
        self.assertIn("-def _get_srcs_file_path", patch)
        self.assertNotIn("+def _get_srcs_file_path", patch)
        self.assertIn("get_out_dir(protos, ctx)", patch)
        self.assertIn("get_proto_arguments(protos, ctx.genfiles_dir.path)", patch)
        self.assertIn('virtual_imports_str = "_virtual_imports"', patch)
        self.assertIn('virtual_includes_path = "_virtual_includes" + rel_path', patch)

    def test_yuanrong_does_not_own_datasystem_dependency_recipes(self):
        self.assertFalse(LEGACY_DATASYSTEM_DEPS.exists())
        self.assertFalse(LEGACY_DATASYSTEM_RECIPES.exists())
        self.assertFalse(LEGACY_PLATFORM_REPOSITORY.exists())
        self.assertFalse(LEGACY_DATASYSTEM_DEPENDENCY_LOADER.exists())
        self.assertFalse(LEGACY_DATASYSTEM_STUB.exists())
        self.assertFalse(LEGACY_DATASYSTEM_RULES.exists())

    def test_datasystem_owns_all_sdk_repository_mappings(self):
        workspace = WORKSPACE.read_text(encoding="utf-8")
        datasystem_workspace = DATASYSTEM_SDK_WORKSPACE.read_text(encoding="utf-8")

        self.assertNotIn("ds_brpc", workspace)
        self.assertNotIn("ds_libzmq", workspace)
        self.assertNotIn("repo_mapping", workspace)
        self.assertIn('"@com_github_apache_brpc": "@ds_brpc"', datasystem_workspace)
        self.assertIn('"@zmq": "@ds_libzmq"', datasystem_workspace)
        self.assertIn("source_sdk_deps(datasystem_repository = name)", datasystem_workspace)

    def test_datasystem_sdk_external_repositories_are_explicitly_accounted_for(self):
        scan_roots = (
            REPO_ROOT / "datasystem" / "bazel" / "sdk",
            REPO_ROOT / "datasystem" / "include" / "datasystem",
            REPO_ROOT / "datasystem" / "src" / "datasystem",
        )
        referenced_repositories = set()
        for scan_root in scan_roots:
            for build_file in scan_root.rglob("BUILD*"):
                text = build_file.read_text(encoding="utf-8")
                referenced_repositories.update(
                    re.findall(
                        r"@([A-Za-z0-9_.+-]+)(?://|(?=[\"',\]\s]))",
                        text,
                    )
                )

        explicitly_accounted_for = {
            "boringssl",
            "com_github_apache_brpc",
            "com_github_grpc_grpc",
            "com_google_absl",
            "com_google_protobuf",
            "curl",
            "ds-spdlog",
            "jemalloc_kvc",
            "local_ascend",
            "local_cuda",
            "mlcachedirect",
            "nlohmann_json",
            "pybind11_bazel",
            "re2",
            "rocksdb",
            "rules_proto",
            "securec",
            "tbb",
            "yuanrong-datasystem",
            "zlib",
            "zmq",
        }
        self.assertEqual(set(), referenced_repositories - explicitly_accounted_for)

    def test_yuanrong_consumers_use_stable_sdk_targets(self):
        expected_labels = {
            REPO_ROOT / "BUILD.bazel": "@datasystem_sdk//bazel/sdk:client",
            REPO_ROOT / "api" / "go" / "BUILD.bazel": "@datasystem_sdk//bazel/sdk:runtime_files",
            REPO_ROOT / "api" / "go" / "libruntime" / "cpplibruntime" / "BUILD.bazel": (
                "@datasystem_sdk//bazel/sdk:client"
            ),
            REPO_ROOT / "api" / "java" / "BUILD.bazel": "@datasystem_sdk//bazel/sdk:runtime_files",
            REPO_ROOT / "test" / "libruntime" / "mock" / "BUILD.bazel": (
                "@datasystem_sdk//bazel/sdk:headers"
            ),
        }

        for build_file, expected_label in expected_labels.items():
            with self.subTest(build_file=build_file):
                self.assertIn(expected_label, build_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
