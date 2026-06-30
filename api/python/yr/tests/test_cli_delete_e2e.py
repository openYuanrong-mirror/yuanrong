#!/usr/bin/env python3
# coding=UTF-8
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

"""End-to-end test for ``yr cli`` sandbox delete.

Drives the real ``HTTPClient`` (real ``requests``) against a local HTTP server
that emulates the frontend-exposed instance kill interface, and verifies the
delete request actually goes through ``POST /frontend/v1/instance/kill`` as a
JSON body (no client-side protobuf), carrying a route-less kill request. This is
the e2e contract check required by the task: "ensure delete goes through the
frontend-exposed interface".
"""

import importlib.util
import io
import json
import sys
import threading
import types
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock


KILL_PATH = "/frontend/v1/instance/kill"


class _FastHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that skips the slow reverse-DNS lookup in server_bind."""

    daemon_threads = True

    def server_bind(self):
        # Bypass HTTPServer.server_bind's socket.getfqdn() which can hang for
        # tens of seconds on hosts with slow reverse-DNS.
        from socketserver import TCPServer

        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


class _Recorder:
    def __init__(self):
        self.path = None
        self.body = b""
        self.headers = {}
        self.content_type = None


def _make_handler(recorder):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            recorder.path = self.path
            recorder.body = self.rfile.read(length)
            recorder.headers = {k: v for k, v in self.headers.items()}
            recorder.content_type = self.headers.get("Content-Type")
            # The frontend transcodes JSON to protobuf internally and replies with a
            # JSON KillResponse. Emulate a success ({"code": 0}).
            payload = json.dumps({"code": 0, "message": ""}).encode("utf-8")
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args, **kwargs):
            pass

    return Handler


def _load_scripts_with_real_requests():
    """Load cli/scripts.py with real ``requests`` but stubbed ``click``/``yr``."""
    scripts_path = Path(__file__).resolve().parents[1] / "cli" / "scripts.py"
    spec = importlib.util.spec_from_file_location("yr_cli_scripts_e2e", scripts_path)
    scripts = importlib.util.module_from_spec(spec)

    fake_click = types.ModuleType("click")
    fake_click.option = lambda *a, **k: (lambda f: f)
    fake_click.argument = lambda *a, **k: (lambda f: f)
    fake_click.version_option = lambda *a, **k: (lambda f: f)
    fake_click.pass_context = lambda f: f
    fake_click.Choice = lambda *a, **k: str

    def group_decorator(*args, **kwargs):
        def decorate(func):
            func.command = lambda *a, **k: (lambda cf: cf)
            func.group = group_decorator
            return func
        return decorate

    fake_click.group = group_decorator

    fake_yr = types.ModuleType("yr")
    fake_yr_cli = types.ModuleType("yr.cli")
    fake_yr_cli_exec = types.ModuleType("yr.cli.exec")
    for name in (
        "choose_cp_mode",
        "copy_from_remote",
        "copy_from_remote_streaming",
        "copy_to_remote",
        "copy_to_remote_streaming",
        "run_client",
    ):
        setattr(fake_yr_cli_exec, name, lambda *a, **k: None)

    with mock.patch.dict(
        sys.modules,
        {
            "click": fake_click,
            "yr": fake_yr,
            "yr.cli": fake_yr_cli,
            "yr.cli.exec": fake_yr_cli_exec,
        },
    ):
        spec.loader.exec_module(scripts)
    return scripts


class TestCliDeleteEndToEnd(unittest.TestCase):
    def setUp(self):
        self.recorder = _Recorder()
        self.server = _FastHTTPServer(("127.0.0.1", 0), _make_handler(self.recorder))
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addr = "%s:%d" % self.server.server_address

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_sandbox_delete_goes_through_frontend_kill_interface(self):
        scripts = _load_scripts_with_real_requests()
        setattr(scripts, "__server_address", self.addr)
        setattr(scripts, "__jwt_token", "e2e-token")

        # No real cluster to query for liveness; assert deletion succeeded once the
        # frontend accepted the kill request.
        with (
            mock.patch.object(scripts, "wait_until_sandbox_deleted", return_value=True),
            redirect_stdout(io.StringIO()) as output,
        ):
            scripts.sandbox_delete("instance-e2e-001")

        # The CLI must hit the frontend-exposed instance kill endpoint.
        self.assertEqual(self.recorder.path, KILL_PATH)
        # JWT propagated.
        self.assertEqual(self.recorder.headers.get("X-Auth"), "e2e-token")
        # The body is plain JSON (no client-side protobuf).
        self.assertIn("application/json", self.recorder.content_type or "")
        body = json.loads(self.recorder.body.decode("utf-8"))
        # Route-less kill request: only instanceID + signal, no routing fields.
        self.assertEqual(body["instanceID"], "instance-e2e-001")
        self.assertEqual(body["signal"], 1)
        self.assertNotIn("routeAddress", body)
        self.assertNotIn("proxyID", body)
        self.assertIn("succeed to delete sandbox: instance-e2e-001", output.getvalue())


if __name__ == "__main__":
    unittest.main()
