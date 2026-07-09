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
"""Run a real tunnel interop check against the native Rust runtime."""

import http.server
import logging
import os
import socket
import subprocess
import threading
import time

import httpx

from yr.sandbox.tunnel_client import TunnelClient


LOG = logging.getLogger(__name__)
WS_PORT = 18765
HTTP_PORT = 18766
UPSTREAM_PORT = 18999
STARTUP_RETRIES = 50
STARTUP_SLEEP_SECONDS = 0.1


class InteropHandler(http.server.BaseHTTPRequestHandler):
    """Fake upstream server that the Python TunnelClient forwards to."""

    def handle_get(self):
        body = f"UPSTREAM-OK:{self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_post(self):
        content_length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(content_length)
        body = b"ECHO:" + data
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


setattr(InteropHandler, "do_GET", InteropHandler.handle_get)
setattr(InteropHandler, "do_POST", InteropHandler.handle_post)


def check_result(name, condition, detail, passed, failed):
    if condition:
        passed.append(name)
        LOG.info("[PASS] %s  %s", name, detail)
        return
    failed.append(name)
    LOG.error("[FAIL] %s  %s", name, detail)


def wait_for_runtime():
    for _ in range(STARTUP_RETRIES):
        try:
            socket.create_connection(("127.0.0.1", HTTP_PORT), 0.2).close()
            return
        except OSError:
            time.sleep(STARTUP_SLEEP_SECONDS)
    raise RuntimeError("rrt-runtime HTTP tunnel port did not become ready")


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    upstream = http.server.ThreadingHTTPServer(
        ("127.0.0.1", UPSTREAM_PORT), InteropHandler
    )
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    proc = subprocess.Popen(
        [os.environ.get("RRT_RUNTIME", "rrt-runtime")],
        env={
            **os.environ,
            "RRT_TUNNEL_ONLY": "1",
            "RRT_TUNNEL_WS_PORT": str(WS_PORT),
            "RRT_TUNNEL_HTTP_PORT": str(HTTP_PORT),
        },
    )
    wait_for_runtime()

    tunnel_client = TunnelClient(upstream=f"127.0.0.1:{UPSTREAM_PORT}")
    if not tunnel_client.start(f"ws://127.0.0.1:{WS_PORT}", timeout=10):
        raise RuntimeError("TunnelClient failed to connect to rust server")
    time.sleep(0.5)

    passed = []
    failed = []
    try:
        response = httpx.get(f"http://127.0.0.1:{HTTP_PORT}/probe", timeout=10)
        check_result(
            "GET via tunnel",
            response.status_code == 200 and response.text == "UPSTREAM-OK:/probe",
            f"{response.status_code} {response.text!r}",
            passed,
            failed,
        )
        echo_response = httpx.post(
            f"http://127.0.0.1:{HTTP_PORT}/echo",
            content=b"hello-rust-tunnel",
            timeout=10,
        )
        check_result(
            "POST body via tunnel",
            echo_response.status_code == 200
            and echo_response.text == "ECHO:hello-rust-tunnel",
            f"{echo_response.status_code} {echo_response.text!r}",
            passed,
            failed,
        )
    finally:
        tunnel_client.stop()
        proc.terminate()

    LOG.info("INTEROP RESULT pass=%s fail=%s %s", len(passed), len(failed), failed)
    if failed:
        raise RuntimeError(f"Interop checks failed: {failed}")


if __name__ == "__main__":
    main()
