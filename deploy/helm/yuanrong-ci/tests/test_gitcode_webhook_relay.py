#!/usr/bin/env python3
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

import importlib.util
import hashlib
import hmac
import os
import unittest
from pathlib import Path


def load_relay_module():
    os.environ.setdefault("BUILDKITE_ORGANIZATION", "test-org")
    os.environ.setdefault("BUILDKITE_PIPELINE", "test-pipeline")
    os.environ.setdefault("BUILDKITE_API_TOKEN", "test-token")
    os.environ.setdefault("GITCODE_WEBHOOK_TOKEN", "test-webhook-token")

    app_path = (
        Path(__file__).resolve().parents[1]
        / "files"
        / "gitcode-webhook-relay"
        / "app.py"
    )
    spec = importlib.util.spec_from_file_location("gitcode_webhook_relay", app_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


relay = load_relay_module()


class GitCodeWebhookRelayTest(unittest.TestCase):
    def setUp(self):
        self.original_settings = relay.SETTINGS.copy()
        self.original_trigger_buildkite = relay.trigger_buildkite
        self.original_commit_is_on_remote_branch = relay.commit_is_on_remote_branch
        relay.SETTINGS.update(
            {
                "trigger_mr": True,
                "trigger_push": False,
                "trigger_tag_push": True,
                "tag_patterns": {"[0-9]*", "v[0-9]*"},
                "mr_actions": {"merge"},
                "mr_target_branches": {"feature/sandbox"},
                "skip_wip": True,
                "use_virtual_merge_ref": False,
                "buildkite_repository": "https://gitcode.com/openeuler/yuanrong.git",
                "dedup_ttl_seconds": 900,
                "message_prefix": "Triggered by GitCode",
                "buildkite_env": {},
                "master_tag_path": "/webhook/gitcode/yuanrong-master-tag",
                "master_tag_pipeline": "yuanrong",
                "master_tag_repository": "https://gitcode.com/openeuler/yuanrong.git",
                "master_tag_branch": "master",
                "master_tag_patterns": {"[0-9]*", "v[0-9]*"},
                "master_tag_env": {
                    "ENABLE_LINUX_ARM": "true",
                    "ENABLE_COMPONENT_IMAGE_BUILD": "true",
                },
            }
        )
        relay.BUILD_DEDUP_CACHE.clear()
        self.triggered = []

        def fake_trigger_buildkite(branch, commit, message, extra_env, overrides=None):
            self.triggered.append(
                {
                    "branch": branch,
                    "commit": commit,
                    "message": message,
                    "extra_env": extra_env,
                    "overrides": overrides or {},
                }
            )
            return {"web_url": "https://buildkite.example/build/1", "number": 1}

        relay.trigger_buildkite = fake_trigger_buildkite
        relay.commit_is_on_remote_branch = lambda repository, commit, branch, tag=None: True

    def tearDown(self):
        relay.SETTINGS.clear()
        relay.SETTINGS.update(self.original_settings)
        relay.BUILD_DEDUP_CACHE.clear()
        relay.trigger_buildkite = self.original_trigger_buildkite
        relay.commit_is_on_remote_branch = self.original_commit_is_on_remote_branch

    def merged_update_payload(self):
        return {
            "object_attributes": {
                "action": "update",
                "state": "merged",
                "target_branch": "feature/sandbox",
                "source_branch": "wip/webhook-macos-default",
                "target_branch_commit": {"id": "56336d2c21f5"},
                "last_commit": {"id": "98d3d2e45c12"},
                "iid": 637,
                "work_in_progress": False,
            },
            "project": {"path_with_namespace": "openeuler/yuanrong"},
            "git_target_branch_commit_no": "56336d2c21f5",
        }

    def merge_payload(self):
        payload = self.merged_update_payload()
        payload["object_attributes"]["action"] = "merge"
        return payload

    def test_merge_action_triggers_target_branch_commit(self):
        code, result = relay.handle_merge_request(self.merge_payload())

        self.assertEqual(code, 200)
        self.assertEqual(result["status"], "triggered")
        self.assertEqual(result["branch"], "feature/sandbox")
        self.assertEqual(result["commit"], "56336d2c21f5")
        self.assertEqual(self.triggered[0]["extra_env"]["GITCODE_MR_ACTION"], "merge")

    def test_merged_update_is_filtered(self):
        payload = self.merged_update_payload()
        payload["changes"] = {
            "state": {
                "previous": "opened",
                "current": "merged",
            },
            "updated_at": {
                "previous": "2026-05-21T18:14:51+08:00",
                "current": "2026-05-21T18:14:52+08:00",
            },
        }

        code, result = relay.handle_merge_request(payload)

        self.assertEqual(code, 202)
        self.assertEqual(result["reason"], "merge request action filtered")
        self.assertEqual(result["details"]["action"], "update")
        self.assertEqual(self.triggered, [])

    def test_merged_label_update_is_filtered(self):
        payload = self.merged_update_payload()
        payload["object_attributes"]["update_reason"] = "update label"
        payload["object_attributes"]["act_desc"] = "update_label"
        payload["changes"] = {
            "updated_at": {
                "previous": "2026-05-21T18:36:31+08:00",
                "current": "2026-05-21T18:36:32+08:00",
            },
            "enterprise_labels": {
                "previous": [{"title": "lgtm"}],
                "current": [{"title": "lgtm"}, {"title": "ci_failed"}],
            },
        }

        code, result = relay.handle_merge_request(payload)

        self.assertEqual(code, 202)
        self.assertEqual(result["reason"], "merge request action filtered")
        self.assertEqual(result["details"]["action"], "update")
        self.assertEqual(self.triggered, [])

    def test_duplicate_merged_update_is_skipped_by_target_commit(self):
        first_code, first_result = relay.handle_merge_request(self.merge_payload())
        second = self.merge_payload()
        second["uuid"] = "637_second-delivery"
        second_code, second_result = relay.handle_merge_request(second)

        self.assertEqual(first_code, 200)
        self.assertEqual(first_result["status"], "triggered")
        self.assertEqual(second_code, 202)
        self.assertEqual(second_result["reason"], "duplicate merge request build trigger")
        self.assertEqual(len(self.triggered), 1)

    def test_stable_tag_push_triggers_release_build_version_and_pypi(self):
        code, result = relay.handle_push(
            {
                "ref": "refs/tags/0.7.50",
                "after": "abcdef1234567890",
                "checkout_sha": "abcdef1234567890",
                "uuid": "tag-delivery-1",
                "project": {"path_with_namespace": "openeuler/yuanrong"},
            }
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["status"], "triggered")
        self.assertEqual(result["event"], "tag_push")
        self.assertEqual(result["tag"], "0.7.50")
        self.assertEqual(result["version"], "0.7.50")
        self.assertEqual(self.triggered[0]["branch"], "0.7.50")
        self.assertEqual(self.triggered[0]["commit"], "abcdef1234567890")
        extra_env = self.triggered[0]["extra_env"]
        self.assertEqual(extra_env["BUILD_VERSION"], "0.7.50")
        self.assertEqual(extra_env["YR_BUILD_VERSION"], "0.7.50")
        self.assertEqual(extra_env["BUILDKITE_TAG"], "0.7.50")
        self.assertEqual(extra_env["PUBLISH_TEST_PYPI"], "0")
        self.assertEqual(extra_env["PUBLISH_PYPI"], "1")
        self.assertEqual(extra_env["BUILDKITE_PACKAGE_UPLOAD_ENABLED"], "0")

    def test_prerelease_tag_push_uses_testpypi(self):
        code, result = relay.handle_push(
            {
                "ref": "refs/tags/0.7.40.rc2",
                "after": "abcdef1234567890",
                "checkout_sha": "abcdef1234567890",
                "uuid": "tag-delivery-rc",
                "project": {"path_with_namespace": "openeuler/yuanrong"},
            }
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["status"], "triggered")
        self.assertEqual(result["version"], "0.7.40.rc2")
        extra_env = self.triggered[0]["extra_env"]
        self.assertEqual(extra_env["BUILD_VERSION"], "0.7.40.rc2")
        self.assertEqual(extra_env["PUBLISH_TEST_PYPI"], "1")
        self.assertEqual(extra_env["PUBLISH_PYPI"], "0")
        self.assertEqual(extra_env["BUILDKITE_PACKAGE_UPLOAD_ENABLED"], "0")

    def test_v_prefixed_tag_push_strips_v_for_build_version(self):
        code, result = relay.handle_push(
            {
                "ref": "refs/tags/v0.7.50",
                "after": "abcdef1234567890",
                "checkout_sha": "abcdef1234567890",
                "project": {"path_with_namespace": "openeuler/yuanrong"},
            }
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["version"], "0.7.50")
        self.assertEqual(self.triggered[0]["extra_env"]["BUILD_VERSION"], "0.7.50")

    def test_tag_push_event_kind_routes_to_tag_handler(self):
        code, result = relay.handle_event(
            {
                "object_kind": "tag_push",
                "ref": "refs/tags/0.7.50",
                "after": "abcdef1234567890",
                "project": {"path_with_namespace": "openeuler/yuanrong"},
            }
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["event"], "tag_push")
        self.assertEqual(self.triggered[0]["extra_env"]["BUILD_VERSION"], "0.7.50")

    def test_tag_push_is_deduplicated(self):
        payload = {
            "ref": "refs/tags/0.7.50",
            "after": "abcdef1234567890",
            "checkout_sha": "abcdef1234567890",
            "project": {"path_with_namespace": "openeuler/yuanrong"},
        }

        first_code, _ = relay.handle_push(dict(payload))
        second_code, second_result = relay.handle_push(dict(payload, uuid="tag-delivery-2"))

        self.assertEqual(first_code, 200)
        self.assertEqual(second_code, 202)
        self.assertEqual(second_result["reason"], "duplicate tag build trigger")
        self.assertEqual(len(self.triggered), 1)

    def test_master_tag_endpoint_triggers_master_pipeline(self):
        code, result = relay.handle_master_tag_event(
            {
                "object_kind": "tag_push",
                "ref": "refs/tags/v0.8.0",
                "after": "abcdef1234567890",
                "checkout_sha": "abcdef1234567890",
                "project": {"path_with_namespace": "openeuler/yuanrong"},
            }
        )

        self.assertEqual(code, 200)
        self.assertEqual(result["status"], "triggered")
        self.assertEqual(result["event"], "master_tag_push")
        self.assertEqual(result["branch"], "master")
        self.assertEqual(result["version"], "0.8.0")
        self.assertEqual(self.triggered[0]["branch"], "v0.8.0")
        self.assertEqual(self.triggered[0]["commit"], "abcdef1234567890")
        self.assertEqual(self.triggered[0]["overrides"]["pipeline"], "yuanrong")
        self.assertEqual(
            self.triggered[0]["overrides"]["repository"],
            "https://gitcode.com/openeuler/yuanrong.git",
        )
        self.assertEqual(
            self.triggered[0]["overrides"]["env"]["ENABLE_COMPONENT_IMAGE_BUILD"],
            "true",
        )
        extra_env = self.triggered[0]["extra_env"]
        self.assertEqual(extra_env["GITCODE_EVENT_KIND"], "master_tag_push")
        self.assertEqual(extra_env["BUILD_VERSION"], "0.8.0")
        self.assertEqual(extra_env["PUBLISH_PYPI"], "1")

    def test_master_tag_endpoint_skips_branch_push(self):
        code, result = relay.handle_master_tag_event(
            {
                "object_kind": "push",
                "ref": "refs/heads/master",
                "after": "abcdef1234567890",
                "project": {"path_with_namespace": "openeuler/yuanrong"},
            }
        )

        self.assertEqual(code, 202)
        self.assertEqual(result["reason"], "master tag endpoint requires tag ref")
        self.assertEqual(self.triggered, [])

    def test_master_tag_endpoint_skips_non_master_commit(self):
        relay.commit_is_on_remote_branch = lambda repository, commit, branch, tag=None: False

        code, result = relay.handle_master_tag_event(
            {
                "object_kind": "tag_push",
                "ref": "refs/tags/v0.8.0",
                "after": "abcdef1234567890",
                "checkout_sha": "abcdef1234567890",
                "project": {"path_with_namespace": "openeuler/yuanrong"},
            }
        )

        self.assertEqual(code, 202)
        self.assertEqual(result["reason"], "tag commit is not on master branch")
        self.assertEqual(result["details"]["branch"], "master")
        self.assertEqual(self.triggered, [])

    def test_tag_delete_is_skipped(self):
        code, result = relay.handle_push(
            {
                "ref": "refs/tags/0.7.50",
                "after": "0" * 40,
                "checkout_sha": "0" * 40,
                "project": {"path_with_namespace": "openeuler/yuanrong"},
            }
        )

        self.assertEqual(code, 202)
        self.assertEqual(result["reason"], "tag deletion or missing commit")
        self.assertEqual(self.triggered, [])

    def test_buildkite_repository_overrides_static_buildkite_repo_env(self):
        relay.SETTINGS["buildkite_env"] = {"BUILDKITE_REPO": "https://gitcode.com/yuchaow/yuanrong.git"}

        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = req.data

            class FakeResponse:
                def __enter__(self):
                    return self

                @staticmethod
                def __exit__(exc_type, exc, tb):
                    return False

                @staticmethod
                def read():
                    return b'{"web_url":"https://buildkite.example/build/2","number":2}'

            return FakeResponse()

        original_urlopen = relay.request.urlopen
        relay.request.urlopen = fake_urlopen
        try:
            build = self.original_trigger_buildkite(
                branch="feature/sandbox",
                commit="56336d2c21f5",
                message="test",
                extra_env={},
            )
        finally:
            relay.request.urlopen = original_urlopen

        self.assertEqual(build["number"], 2)
        self.assertIn(
            b'"BUILDKITE_REPO": "https://gitcode.com/openeuler/yuanrong.git"',
            captured["body"],
        )

    def test_open_update_is_still_filtered(self):
        code, result = relay.handle_merge_request(
            {
                "object_attributes": {
                    "action": "update",
                    "state": "opened",
                    "target_branch": "feature/sandbox",
                    "source_branch": "wip/webhook-macos-default",
                    "last_commit": {"id": "98d3d2e45c12"},
                    "iid": 637,
                    "work_in_progress": False,
                },
                "project": {"path_with_namespace": "openeuler/yuanrong"},
            }
        )

        self.assertEqual(code, 202)
        self.assertEqual(result["reason"], "merge request action filtered")
        self.assertEqual(result["details"]["action"], "update")
        self.assertEqual(self.triggered, [])

    def test_webhook_token_is_valid_when_signature_secret_is_also_set(self):
        relay.SETTINGS["webhook_token"] = "gitcode-password"
        relay.SETTINGS["signature_secret"] = "configured-signature-secret"

        for header in ("X-GitCode-Token", "X-Gitlab-Token", "X-GitLab-Token", "X-Gitee-Token"):
            with self.subTest(header=header):
                self.assertTrue(
                    relay.verify_request(
                        b"{}",
                        {header: "gitcode-password"},
                    )
                )

    def test_empty_webhook_token_does_not_allow_missing_token_header(self):
        relay.SETTINGS["webhook_token"] = ""
        relay.SETTINGS["signature_secret"] = "configured-signature-secret"

        self.assertFalse(relay.verify_request(b"{}", {}))

    def test_valid_signature_is_accepted_before_token_fallback(self):
        body = b'{"object_kind":"merge_request"}'
        relay.SETTINGS["webhook_token"] = "gitcode-password"
        relay.SETTINGS["signature_secret"] = "configured-signature-secret"
        signature = "sha256=" + hmac.new(
            relay.SETTINGS["signature_secret"].encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        self.assertTrue(
            relay.verify_request(
                body,
                {
                    "X-GitCode-Signature-256": signature,
                    "X-GitCode-Token": "wrong-token",
                },
            )
        )


if __name__ == "__main__":
    unittest.main()
