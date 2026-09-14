# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import pathlib
import subprocess
import tempfile
import unittest

from test_yr_k8s_layout import (
    BASH_BIN,
    PYTHON_BIN,
    ROOT,
    emit_dynamic_pipeline,
    index_pipeline_steps,
    pipeline_step_container,
)


class YrK8sPipelineContractsTests(unittest.TestCase):
    def test_sandbox_image_executors_and_dependencies(self):
        packager = "registry.example.com/openyuanrong/sandbox-packager:test"
        steps = index_pipeline_steps(emit_dynamic_pipeline(
            SANDBOX_PACKAGER_IMAGE=packager,
            ENABLE_SANDBOX_K8S_TEST="false",
            ENABLE_TEST_PYPI_PUBLISH="false",
        ))
        for arch in ("amd64", "arm64"):
            step = steps[f"publish-sandbox-release-{arch}"]
            self.assertEqual(set(step["depends_on"]), {
                f"build-all-{arch}", f"build-rrt-{arch}", f"build-data-plane-gateway-{arch}",
            })
            minor = "3.11" if arch == "amd64" else "3.9"
            self.assertEqual(step["env"]["YR_K8S_PYTHON_MAJOR_MINOR"], minor)
            self.assertIn(f"/opt/buildtools/python{minor}/bin", steps[f"build-all-{arch}"]["command"])
        self.assertEqual(pipeline_step_container(steps["publish-sandbox-release-amd64"])["image"], packager)
        self.assertEqual(steps["publish-sandbox-release-arm64"]["agents"]["linux_arch"], "arm64")
        self.assertEqual(set(steps["publish-sandbox-manifest"]["depends_on"]), {
            "publish-sandbox-release-amd64", "publish-sandbox-release-arm64", "test-sandbox-sdk",
        })

    def test_runtime_package_requires_current_arch_rrt_artifact(self):
        source = (ROOT.parents[2] / ".buildkite/package_sandbox_release.sh").read_text()
        for arch, wheel_arch, available in (("amd64", "x86_64", True),
                                            ("arm64", "aarch64", True),
                                            ("amd64", "x86_64", False)):
            with self.subTest(arch=arch, available=available), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                scripts = root / ".buildkite"
                scripts.mkdir()
                library = scripts / "package_sandbox_release.sh"
                library.write_text(source.rsplit('\nmain "$@"', 1)[0] + "\n")
                fake = root / "buildkite-agent"
                fake.write_text(
                    "#!/bin/bash\nset -eu\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
                    'test "$1" = artifact && test "$2" = download\n'
                    'if [ "$AVAILABLE" = true ]; then mkdir -p "$4"; touch "$4/$WHEEL"; fi\n'
                )
                fake.chmod(0o755)
                wheel = f"openyuanrong_rrt-0.10.3-py3-none-manylinux_2_17_{wheel_arch}.whl"
                env = dict(os.environ, PATH=f"{root}:/usr/bin:/bin",
                           YR_K8S_RUNTIME_ONLY="1", YR_K8S_IMAGE_ARCH=arch,
                           AVAILABLE=str(available).lower(), WHEEL=wheel,
                           BUILDKITE_COMMIT="a" * 40, BUILDKITE_BRANCH="test",
                           CALL_LOG=str(root / "calls.log"))
                result = subprocess.run(
                    [str(BASH_BIN), "-c", 'source "$1"; download_release_artifacts', "bash", str(library)],
                    cwd=root, env=env, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode == 0, available, result.stderr)
                self.assertEqual((root / "calls.log").read_text().splitlines(), [
                    f"artifact download openyuanrong_rrt-*_{wheel_arch}.whl {root}/output/",
                ])
                self.assertEqual((root / "output" / wheel).is_file(), available)
                if not available:
                    self.assertIn("Missing required RRT wheel", result.stderr)

    def test_image_manifest_validator_rejects_wrong_platform_and_duplicates(self):
        verifier = ROOT.parents[2] / ".buildkite/verify_image_manifest.py"
        self.assertTrue(verifier.is_file())
        digest_amd64 = "sha256:" + "a" * 64
        digest_arm64 = "sha256:" + "b" * 64
        final_digest = "sha256:" + "c" * 64
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = pathlib.Path(tmpdir)
            source = tmp / "source.json"
            source.write_text(
                json.dumps(
                    {
                        "Descriptor": {
                            "digest": digest_amd64,
                            "platform": {"os": "linux", "architecture": "amd64"},
                        }
                    }
                )
            )
            evidence = tmp / "evidence.tsv"
            source_args = [
                str(PYTHON_BIN),
                str(verifier),
                "source",
                "--input",
                str(source),
                "--image",
                "registry.example.com/yr-runtime:test-amd64",
                "--evidence",
                str(evidence),
            ]
            subprocess.run(
                [*source_args, "--expected-platform", "linux/amd64"],
                check=True,
                capture_output=True,
                text=True,
            )
            wrong_source = subprocess.run(
                [*source_args, "--expected-platform", "linux/arm64"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(wrong_source.returncode, 0)

            final = tmp / "final.json"
            final.write_text(
                json.dumps(
                    {
                        "manifests": [
                            {
                                "digest": digest_amd64,
                                "platform": {"os": "linux", "architecture": "amd64"},
                            },
                            {
                                "digest": digest_arm64,
                                "platform": {"os": "linux", "architecture": "arm64"},
                            },
                        ]
                    }
                )
            )
            final_args = [
                str(PYTHON_BIN),
                str(verifier),
                "final",
                "--input",
                str(final),
                "--image",
                "registry.example.com/yr-runtime:test",
                "--digest",
                final_digest,
                "--expected-platform",
                "linux/amd64",
                "--expected-platform",
                "linux/arm64",
                "--evidence",
                str(evidence),
            ]
            subprocess.run(final_args, check=True, capture_output=True, text=True)
            duplicate = json.loads(final.read_text())
            duplicate["manifests"][1]["platform"]["architecture"] = "amd64"
            final.write_text(json.dumps(duplicate))
            wrong_final = subprocess.run(final_args, check=False, capture_output=True, text=True)
            self.assertNotEqual(wrong_final.returncode, 0)
            evidence_text = evidence.read_text()
            self.assertIn(digest_amd64, evidence_text)
            self.assertIn(final_digest, evidence_text)
            self.assertIn("linux/amd64,linux/arm64", evidence_text)


    def test_push_images_falls_back_when_platform_push_is_unsupported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            docker_log = pathlib.Path(tmpdir) / "docker.log"
            fake_docker = pathlib.Path(tmpdir) / "docker"
            fake_docker.write_text(
                "#!/usr/bin/env bash\n"
                "echo \"$*\" >> \"${DOCKER_LOG}\"\n"
                "if [ \"$1\" = push ] && [ \"${2:-}\" = --help ]; then\n"
                "  echo 'Usage: docker push NAME[:TAG]'\n"
                "  exit 0\n"
                "fi\n"
                "if [ \"$1\" = image ] && [ \"${2:-}\" = inspect ]; then exit 0; fi\n"
                "if [ \"$1\" = push ] && [ \"${2:-}\" = --platform ]; then exit 42; fi\n"
                "exit 0\n"
            )
            fake_docker.chmod(0o755)
            result = subprocess.run(
                [str(ROOT / "push-images-swr.sh")],
                cwd=ROOT.parents[2],
                check=True,
                capture_output=True,
                text=True,
                env={
                    "PATH": f"{tmpdir}:/usr/bin:/bin",
                    "DOCKER_BIN": str(fake_docker),
                    "DOCKER_LOG": str(docker_log),
                    "YR_K8S_REGISTRY_REPO": "registry.example.com/openyuanrong",
                    "YR_K8S_IMAGE_TAG": "test-tag",
                    "YR_K8S_IMAGE_PLATFORM": "linux/arm64",
                    "YR_K8S_IMAGE_CACHE": "1",
                    "YR_K8S_IMAGE_CACHE_TAG": "cache-arm64",
                },
            )

            log_text = docker_log.read_text()
            self.assertNotIn("push --platform", log_text)
            self.assertIn("push registry.example.com/openyuanrong/yr-base:test-tag", log_text)
            self.assertIn("push registry.example.com/openyuanrong/yr-base:cache-arm64", log_text)
            self.assertIn("without platform flag", result.stderr)


if __name__ == "__main__":
    unittest.main()
