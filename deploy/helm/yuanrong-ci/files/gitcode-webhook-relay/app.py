#!/usr/bin/env python3

import hashlib
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, request


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_csv(name):
    value = os.getenv(name, "")
    return {item.strip() for item in value.split(",") if item.strip()}


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
    "message_prefix": os.getenv("BUILDKITE_MESSAGE_PREFIX", "Triggered by GitCode"),
    "buildkite_env": json.loads(os.getenv("BUILDKITE_ENV_JSON", "{}")),
    "trigger_push": env_bool("RELAY_TRIGGER_PUSH", True),
    "trigger_mr": env_bool("RELAY_TRIGGER_MERGE_REQUEST", True),
    "push_branches": env_csv("RELAY_ALLOWED_PUSH_BRANCHES"),
    "mr_target_branches": env_csv("RELAY_ALLOWED_MR_TARGET_BRANCHES"),
    "mr_actions": env_csv("RELAY_ALLOWED_MR_ACTIONS"),
    "skip_wip": env_bool("RELAY_SKIP_WORK_IN_PROGRESS", True),
    "use_virtual_merge_ref": env_bool("RELAY_USE_VIRTUAL_MERGE_REF", False),
    "webhook_token": os.getenv("GITCODE_WEBHOOK_TOKEN", ""),
    "signature_secret": os.getenv("GITCODE_WEBHOOK_SIGNATURE_SECRET", ""),
}

if not isinstance(SETTINGS["buildkite_env"], dict):
    raise RuntimeError("BUILDKITE_ENV_JSON must decode to a JSON object")

if not SETTINGS["webhook_token"] and not SETTINGS["signature_secret"]:
    raise RuntimeError("Either GITCODE_WEBHOOK_TOKEN or GITCODE_WEBHOOK_SIGNATURE_SECRET is required")


def verify_request(body, headers):
    signature_secret = SETTINGS["signature_secret"]
    if signature_secret:
        received = headers.get("X-GitCode-Signature-256", "")
        expected = "sha256=" + hmac.new(
            signature_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(received, expected)

    token = SETTINGS["webhook_token"]
    received = headers.get("X-GitCode-Token", "")
    return hmac.compare_digest(received, token)


def respond(handler, code, payload):
    data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def parse_push_branch(ref):
    prefix = "refs/heads/"
    return ref[len(prefix):] if ref.startswith(prefix) else ref


def trigger_buildkite(branch, commit, message, extra_env):
    payload = {
        "branch": branch,
        "commit": commit,
        "message": message,
        "env": {**SETTINGS["buildkite_env"], **extra_env},
    }
    url = (
        "https://api.buildkite.com/v2/organizations/"
        f"{SETTINGS['buildkite_org']}/pipelines/{SETTINGS['buildkite_pipeline']}/builds"
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


def handle_push(payload):
    if not SETTINGS["trigger_push"]:
        return skip_response("push trigger disabled")

    ref = payload.get("ref", "")
    branch = parse_push_branch(ref)
    if SETTINGS["push_branches"] and branch not in SETTINGS["push_branches"]:
        return skip_response("push branch filtered", {"branch": branch})

    commit = payload.get("checkout_sha") or payload.get("after")
    if not commit:
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
    message = (
        f"{SETTINGS['message_prefix']}: mr !{iid} {action} "
        f"{source_branch}->{target_branch} {commit[:12]}"
    )
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
    if kind == "push":
        return handle_push(payload)
    if kind == "merge_request":
        return handle_merge_request(payload)
    return skip_response("unsupported event kind", {"object_kind": kind})


class RelayHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stdout.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))
        sys.stdout.flush()

    def do_GET(self):
        if self.path.rstrip("/") in {"", "/healthz", "/readyz"}:
            respond(self, 200, {"status": "ok"})
            return
        respond(self, 404, {"status": "error", "reason": "not found"})

    def do_POST(self):
        normalized = self.path.rstrip("/") or "/"
        if normalized != SETTINGS["path"]:
            respond(self, 404, {"status": "error", "reason": "not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)

        if not verify_request(body, self.headers):
            respond(self, 401, {"status": "error", "reason": "invalid webhook signature"})
            return

        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            respond(self, 400, {"status": "error", "reason": "invalid json"})
            return

        try:
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


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", SETTINGS["port"]), RelayHandler)
    print(
        f"gitcode-webhook-relay listening on :{SETTINGS['port']} path={SETTINGS['path']}",
        flush=True,
    )
    server.serve_forever()
