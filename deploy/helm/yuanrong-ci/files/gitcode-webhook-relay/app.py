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

import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from fnmatch import fnmatchcase
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, request

LOGGER = logging.getLogger(__name__)


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_csv(name):
    value = os.getenv(name, "")
    return {item.strip() for item in value.split(",") if item.strip()}


def env_int(name, default):
    value = os.getenv(name, "")
    if not value.strip():
        return default
    return int(value)


def env_json_object(name, default=None):
    value = os.getenv(name, "")
    if not value.strip():
        return {} if default is None else default
    data = json.loads(value)
    if not isinstance(data, dict):
        raise RuntimeError(f"{name} must decode to a JSON object")
    return data


def require_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


SETTINGS = {
    "port": int(os.getenv("PORT", "8080")),
    "path": os.getenv("RELAY_PATH", "/webhook/gitcode").rstrip("/") or "/",
    "buildkite_org": require_env("BUILDKITE_ORGANIZATION"),
    "buildkite_pipeline": require_env("BUILDKITE_PIPELINE"),
    "buildkite_token": require_env("BUILDKITE_API_TOKEN"),
    "buildkite_repository": os.getenv("BUILDKITE_REPOSITORY", "").strip(),
    "message_prefix": os.getenv("BUILDKITE_MESSAGE_PREFIX", "Triggered by GitCode"),
    "buildkite_env": json.loads(os.getenv("BUILDKITE_ENV_JSON", "{}")),
    "trigger_push": env_bool("RELAY_TRIGGER_PUSH", True),
    "trigger_tag_push": env_bool("RELAY_TRIGGER_TAG_PUSH", True),
    "trigger_mr": env_bool("RELAY_TRIGGER_MERGE_REQUEST", True),
    "push_branches": env_csv("RELAY_ALLOWED_PUSH_BRANCHES"),
    "tag_patterns": env_csv("RELAY_ALLOWED_TAG_PATTERNS"),
    "mr_target_branches": env_csv("RELAY_ALLOWED_MR_TARGET_BRANCHES"),
    "mr_actions": env_csv("RELAY_ALLOWED_MR_ACTIONS"),
    "skip_wip": env_bool("RELAY_SKIP_WORK_IN_PROGRESS", True),
    "use_virtual_merge_ref": env_bool("RELAY_USE_VIRTUAL_MERGE_REF", False),
    "dedup_ttl_seconds": env_int("RELAY_DEDUP_TTL_SECONDS", 900),
    "webhook_token": os.getenv("GITCODE_WEBHOOK_TOKEN", ""),
    "signature_secret": os.getenv("GITCODE_WEBHOOK_SIGNATURE_SECRET", ""),
    "master_tag_path": os.getenv("RELAY_MASTER_TAG_PATH", "").rstrip("/"),
    "master_tag_pipeline": os.getenv("RELAY_MASTER_TAG_BUILDKITE_PIPELINE", "").strip(),
    "master_tag_repository": os.getenv("RELAY_MASTER_TAG_REPOSITORY", "").strip(),
    "master_tag_branch": os.getenv("RELAY_MASTER_TAG_BRANCH", "master").strip() or "master",
    "master_tag_patterns": env_csv("RELAY_MASTER_TAG_PATTERNS"),
    "master_tag_env": env_json_object("RELAY_MASTER_TAG_ENV_JSON"),
    "git_timeout_seconds": env_int("RELAY_GIT_TIMEOUT_SECONDS", 120),
}

if not isinstance(SETTINGS["buildkite_env"], dict):
    raise RuntimeError("BUILDKITE_ENV_JSON must decode to a JSON object")

if not SETTINGS["webhook_token"] and not SETTINGS["signature_secret"]:
    raise RuntimeError("Either GITCODE_WEBHOOK_TOKEN or GITCODE_WEBHOOK_SIGNATURE_SECRET is required")

if SETTINGS["master_tag_path"]:
    if not SETTINGS["master_tag_pipeline"]:
        raise RuntimeError("RELAY_MASTER_TAG_BUILDKITE_PIPELINE is required when RELAY_MASTER_TAG_PATH is set")
    if not SETTINGS["master_tag_repository"]:
        raise RuntimeError("RELAY_MASTER_TAG_REPOSITORY is required when RELAY_MASTER_TAG_PATH is set")


BUILD_DEDUP_CACHE = {}
BUILD_DEDUP_LOCK = threading.Lock()


def verify_request(body, headers):
    signature_secret = SETTINGS["signature_secret"]
    if signature_secret:
        received = headers.get("X-GitCode-Signature-256", "")
        expected = "sha256=" + hmac.new(
            signature_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        if hmac.compare_digest(received, expected):
            return True

    token = SETTINGS["webhook_token"]
    if not token:
        return False

    for header in ("X-GitCode-Token", "X-Gitlab-Token", "X-GitLab-Token", "X-Gitee-Token"):
        received = headers.get(header, "")
        if received and hmac.compare_digest(received, token):
            return True

    return False


def auth_failure_details(headers):
    return {
        "token_configured": bool(SETTINGS["webhook_token"]),
        "signature_secret_configured": bool(SETTINGS["signature_secret"]),
        "auth_headers_present": sorted(
            key
            for key in headers.keys()
            if key.lower().startswith("x-git") or key.lower() in {"x-hub-signature-256"}
        ),
    }


def respond(handler, code, payload):
    data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def parse_push_ref(ref):
    if ref.startswith("refs/heads/"):
        return "branch", ref[len("refs/heads/"):]
    if ref.startswith("refs/tags/"):
        return "tag", ref[len("refs/tags/"):]
    return "unknown", ref


def normalize_tag_version(tag):
    if tag.startswith("v") and len(tag) > 1 and tag[1].isdigit():
        return tag[1:]
    return tag


def is_prerelease_version(version):
    return bool(re.search(r"(?i)(?:a|alpha|b|beta|rc|dev)\d+", version))


def is_zero_commit(commit):
    return bool(commit) and set(commit) == {"0"}


def reserve_build_key(build_key):
    ttl = SETTINGS["dedup_ttl_seconds"]
    if not build_key or ttl <= 0:
        return True

    now = time.time()
    expires_at = now + ttl
    with BUILD_DEDUP_LOCK:
        expired = [key for key, value in BUILD_DEDUP_CACHE.items() if value <= now]
        for key in expired:
            del BUILD_DEDUP_CACHE[key]
        if build_key in BUILD_DEDUP_CACHE:
            return False
        BUILD_DEDUP_CACHE[build_key] = expires_at
        return True


def release_build_key(build_key):
    if not build_key:
        return
    with BUILD_DEDUP_LOCK:
        BUILD_DEDUP_CACHE.pop(build_key, None)


def trigger_buildkite(branch, commit, message, extra_env, overrides=None):
    overrides = overrides or {}
    repository = overrides.get("repository", SETTINGS["buildkite_repository"])
    pipeline = overrides.get("pipeline", SETTINGS["buildkite_pipeline"])
    build_env = {**SETTINGS["buildkite_env"], **overrides.get("env", {}), **extra_env}
    if repository:
        build_env["BUILDKITE_REPO"] = repository

    payload = {
        "branch": branch,
        "commit": commit,
        "message": message,
        "env": build_env,
    }
    url = (
        "https://api.buildkite.com/v2/organizations/"
        f"{SETTINGS['buildkite_org']}/pipelines/{pipeline}/builds"
    )
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {SETTINGS['buildkite_token']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def skip_response(reason, details=None):
    payload = {"status": "skipped", "reason": reason}
    if details:
        payload["details"] = details
    return 202, payload


def run_git(args, cwd):
    cmd = ["git", *args]
    LOGGER.info("running git command: %s", " ".join(cmd))
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=SETTINGS["git_timeout_seconds"],
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git command failed: {' '.join(cmd)}; "
            f"stdout={completed.stdout.strip()}; stderr={completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def commit_is_on_remote_branch(repository, commit, branch, tag=None):
    work_dir = tempfile.mkdtemp(prefix="gitcode-relay-")
    try:
        run_git(["init", "--bare", "."], work_dir)
        run_git(["remote", "add", "origin", repository], work_dir)
        run_git(["fetch", "--filter=blob:none", "origin", branch], work_dir)
        if tag:
            run_git(["fetch", "--filter=blob:none", "origin", f"refs/tags/{tag}:refs/tags/{tag}"], work_dir)
        else:
            run_git(["fetch", "--filter=blob:none", "origin", commit], work_dir)
        completed = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, f"origin/{branch}"],
            cwd=work_dir,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=SETTINGS["git_timeout_seconds"],
            check=False,
        )
        if completed.returncode == 0:
            return True
        if completed.returncode == 1:
            return False
        raise RuntimeError(
            "git merge-base failed: "
            f"stdout={completed.stdout.strip()}; stderr={completed.stderr.strip()}"
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def handle_push(payload):
    ref = payload.get("ref", "")
    ref_kind, ref_name = parse_push_ref(ref)
    if ref_kind == "tag":
        return handle_tag_push(payload, ref_name)
    if ref_kind != "branch":
        return skip_response("unsupported push ref", {"ref": ref})

    if not SETTINGS["trigger_push"]:
        return skip_response("push trigger disabled")

    branch = ref_name
    if SETTINGS["push_branches"] and branch not in SETTINGS["push_branches"]:
        return skip_response("push branch filtered", {"branch": branch})

    commit = payload.get("checkout_sha") or payload.get("after")
    if not commit or is_zero_commit(commit):
        return 400, {"status": "error", "reason": "missing push commit sha"}

    project = payload.get("project", {}).get("path_with_namespace", "")
    message = f"{SETTINGS['message_prefix']}: push {project} {branch} {commit[:12]}"
    build = trigger_buildkite(
        branch=branch,
        commit=commit,
        message=message,
        extra_env={
            "GITCODE_EVENT_KIND": "push",
            "GITCODE_PROJECT_PATH": project,
            "GITCODE_REF": ref,
            "GITCODE_BRANCH": branch,
            "GITCODE_EVENT_UUID": payload.get("uuid", ""),
        },
    )
    return 200, {
        "status": "triggered",
        "event": "push",
        "branch": branch,
        "commit": commit,
        "build_url": build.get("web_url"),
        "build_number": build.get("number"),
    }


def handle_tag_push(payload, tag):
    if not SETTINGS["trigger_tag_push"]:
        return skip_response("tag push trigger disabled")
    if SETTINGS["tag_patterns"] and not any(fnmatchcase(tag, pattern) for pattern in SETTINGS["tag_patterns"]):
        return skip_response("tag filtered", {"tag": tag})

    commit = payload.get("checkout_sha") or payload.get("after")
    if not commit or is_zero_commit(commit):
        return skip_response("tag deletion or missing commit", {"tag": tag})

    project = payload.get("project", {}).get("path_with_namespace", "")
    build_version = normalize_tag_version(tag)
    build_key = f"tag_push:{tag}:{commit}"
    if not reserve_build_key(build_key):
        return skip_response("duplicate tag build trigger", {"tag": tag, "commit": commit})

    message = f"{SETTINGS['message_prefix']}: tag {project} {tag} {commit[:12]}"
    publish_env = {
        "PUBLISH_TEST_PYPI": "1",
        "PUBLISH_PYPI": "0",
    }
    if not is_prerelease_version(build_version):
        publish_env = {
            "PUBLISH_TEST_PYPI": "0",
            "PUBLISH_PYPI": "1",
        }
    try:
        build = trigger_buildkite(
            branch=tag,
            commit=commit,
            message=message,
            extra_env={
                "GITCODE_EVENT_KIND": "tag_push",
                "GITCODE_PROJECT_PATH": project,
                "GITCODE_REF": payload.get("ref", ""),
                "GITCODE_TAG": tag,
                "BUILDKITE_TAG": tag,
                "YR_RELEASE_TAG": tag,
                "BUILD_VERSION": build_version,
                "YR_BUILD_VERSION": build_version,
                **publish_env,
                "BUILDKITE_PACKAGE_UPLOAD_ENABLED": "0",
                "GITCODE_EVENT_UUID": payload.get("uuid", ""),
            },
        )
    except (RuntimeError, ValueError, error.URLError):
        release_build_key(build_key)
        raise

    return 200, {
        "status": "triggered",
        "event": "tag_push",
        "tag": tag,
        "version": build_version,
        "commit": commit,
        "build_url": build.get("web_url"),
        "build_number": build.get("number"),
    }


def handle_master_tag_push(payload, tag):
    patterns = SETTINGS["master_tag_patterns"] or SETTINGS["tag_patterns"]
    if patterns and not any(fnmatchcase(tag, pattern) for pattern in patterns):
        return skip_response("master tag filtered", {"tag": tag})

    commit = payload.get("checkout_sha") or payload.get("after")
    if not commit or is_zero_commit(commit):
        return skip_response("tag deletion or missing commit", {"tag": tag})

    repository = SETTINGS["master_tag_repository"]
    branch = SETTINGS["master_tag_branch"]
    if not commit_is_on_remote_branch(repository, commit, branch, tag=tag):
        return skip_response(
            "tag commit is not on master branch",
            {"tag": tag, "commit": commit, "branch": branch},
        )

    project = payload.get("project", {}).get("path_with_namespace", "")
    build_version = normalize_tag_version(tag)
    build_key = f"master_tag_push:{tag}:{commit}"
    if not reserve_build_key(build_key):
        return skip_response("duplicate master tag build trigger", {"tag": tag, "commit": commit})

    message = f"{SETTINGS['message_prefix']}: master tag {project} {tag} {commit[:12]}"
    publish_env = {
        "PUBLISH_TEST_PYPI": "1",
        "PUBLISH_PYPI": "0",
    }
    if not is_prerelease_version(build_version):
        publish_env = {
            "PUBLISH_TEST_PYPI": "0",
            "PUBLISH_PYPI": "1",
        }
    try:
        build = trigger_buildkite(
            branch=tag,
            commit=commit,
            message=message,
            extra_env={
                "GITCODE_EVENT_KIND": "master_tag_push",
                "GITCODE_PROJECT_PATH": project,
                "GITCODE_REF": payload.get("ref", ""),
                "GITCODE_TAG": tag,
                "BUILDKITE_TAG": tag,
                "YR_RELEASE_TAG": tag,
                "BUILD_VERSION": build_version,
                "YR_BUILD_VERSION": build_version,
                **publish_env,
                "GITCODE_EVENT_UUID": payload.get("uuid", ""),
            },
            overrides={
                "pipeline": SETTINGS["master_tag_pipeline"],
                "repository": repository,
                "env": SETTINGS["master_tag_env"],
            },
        )
    except (RuntimeError, ValueError, error.URLError):
        release_build_key(build_key)
        raise

    return 200, {
        "status": "triggered",
        "event": "master_tag_push",
        "tag": tag,
        "version": build_version,
        "commit": commit,
        "branch": branch,
        "build_url": build.get("web_url"),
        "build_number": build.get("number"),
    }


def handle_merge_request(payload):
    if not SETTINGS["trigger_mr"]:
        return skip_response("merge request trigger disabled")

    attrs = payload.get("object_attributes", {})
    action = attrs.get("action", "")
    target_branch = attrs.get("target_branch", "")
    source_branch = attrs.get("source_branch", "")

    if SETTINGS["mr_actions"] and action not in SETTINGS["mr_actions"]:
        return skip_response("merge request action filtered", {"action": action})
    if SETTINGS["mr_target_branches"] and target_branch not in SETTINGS["mr_target_branches"]:
        return skip_response(
            "merge request target branch filtered", {"target_branch": target_branch}
        )
    if SETTINGS["skip_wip"] and attrs.get("work_in_progress", False):
        return skip_response("merge request is work in progress")

    if action == "merge":
        branch = target_branch
        commit = (
            payload.get("git_target_branch_commit_no")
            or attrs.get("target_branch_commit", {}).get("id")
            or payload.get("git_commit_no", "")
        )
    elif SETTINGS["use_virtual_merge_ref"] and payload.get("git_branch") and payload.get("git_commit_no"):
        branch = payload["git_branch"]
        commit = payload["git_commit_no"]
    else:
        branch = source_branch
        commit = attrs.get("last_commit", {}).get("id") or payload.get("git_commit_no", "")

    if not branch or not commit:
        return 400, {"status": "error", "reason": "missing merge request branch or commit"}

    iid = attrs.get("iid", "")
    project = payload.get("project", {}).get("path_with_namespace", "")
    build_key = f"merge_request:{iid}:{action}:{source_branch}:{target_branch}:{commit}"
    if not reserve_build_key(build_key):
        return skip_response(
            "duplicate merge request build trigger",
            {"iid": iid, "action": action, "target_branch": target_branch, "commit": commit},
        )
    message = (
        f"{SETTINGS['message_prefix']}: mr !{iid} {action} "
        f"{source_branch}->{target_branch} {commit[:12]}"
    )
    try:
        build = trigger_buildkite(
            branch=branch,
            commit=commit,
            message=message,
            extra_env={
                "GITCODE_EVENT_KIND": "merge_request",
                "GITCODE_PROJECT_PATH": project,
                "GITCODE_MR_IID": str(iid),
                "GITCODE_MR_ACTION": action,
                "GITCODE_MR_SOURCE_BRANCH": source_branch,
                "GITCODE_MR_TARGET_BRANCH": target_branch,
                "GITCODE_MR_URL": attrs.get("url", ""),
                "GITCODE_EVENT_UUID": payload.get("uuid", ""),
            },
        )
    except (RuntimeError, ValueError, error.URLError):
        release_build_key(build_key)
        raise
    return 200, {
        "status": "triggered",
        "event": "merge_request",
        "branch": branch,
        "commit": commit,
        "build_url": build.get("web_url"),
        "build_number": build.get("number"),
    }


def handle_event(payload):
    kind = payload.get("object_kind") or payload.get("event_type") or payload.get("event_name")
    if kind in {"push", "tag_push"}:
        return handle_push(payload)
    if kind == "merge_request":
        return handle_merge_request(payload)
    return skip_response("unsupported event kind", {"object_kind": kind})


def handle_master_tag_event(payload):
    kind = payload.get("object_kind") or payload.get("event_type") or payload.get("event_name")
    if kind not in {"push", "tag_push"}:
        return skip_response("unsupported master tag event kind", {"object_kind": kind})
    ref = payload.get("ref", "")
    ref_kind, ref_name = parse_push_ref(ref)
    if ref_kind != "tag":
        return skip_response("master tag endpoint requires tag ref", {"ref": ref})
    return handle_master_tag_push(payload, ref_name)


class RelayHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        LOGGER.info(
            "%s - - [%s] %s",
            self.address_string(),
            self.log_date_time_string(),
            fmt % args,
        )

    def handle_get(self):
        if self.path.rstrip("/") in {"", "/healthz", "/readyz"}:
            respond(self, 200, {"status": "ok"})
            return
        respond(self, 404, {"status": "error", "reason": "not found"})

    def handle_post(self):
        normalized = self.path.rstrip("/") or "/"
        if normalized == SETTINGS["path"]:
            route = "default"
        elif SETTINGS["master_tag_path"] and normalized == SETTINGS["master_tag_path"]:
            route = "master_tag"
        else:
            respond(self, 404, {"status": "error", "reason": "not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)

        if not verify_request(body, self.headers):
            self.log_message("webhook auth failed: %s", json.dumps(auth_failure_details(self.headers), sort_keys=True))
            respond(self, 401, {"status": "error", "reason": "invalid webhook authentication"})
            return

        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            respond(self, 400, {"status": "error", "reason": "invalid json"})
            return

        try:
            if route == "master_tag":
                code, result = handle_master_tag_event(payload)
            else:
                code, result = handle_event(payload)
            respond(self, code, result)
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            respond(
                self,
                502,
                {
                    "status": "error",
                    "reason": "buildkite trigger failed",
                    "code": exc.code,
                    "details": details,
                },
            )
        except Exception as exc:
            respond(self, 500, {"status": "error", "reason": str(exc)})


RelayHandler.do_GET = RelayHandler.handle_get
RelayHandler.do_POST = RelayHandler.handle_post


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    server = ThreadingHTTPServer(("0.0.0.0", SETTINGS["port"]), RelayHandler)
    LOGGER.info(
        "gitcode-webhook-relay listening on :%s path=%s master_tag_path=%s",
        SETTINGS["port"],
        SETTINGS["path"],
        SETTINGS["master_tag_path"] or "<disabled>",
    )
    server.serve_forever()
