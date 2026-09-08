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

"""Live sandbox-sdk matrix through the Rust Edge/Node data plane."""

from __future__ import annotations

import asyncio
import hashlib
import http.server
import io
import json
import logging
import os
import ssl
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import asdict
from pathlib import Path

from yr_sandbox import Sandbox, resources

PASSED: list[str] = []
FAILED: list[str] = []
DETAILS: dict[str, object] = {}


def check(name: str, condition: bool, detail: object = None) -> None:
    (PASSED if condition else FAILED).append(name)
    if detail is not None:
        DETAILS[name] = detail
    logging.info(
        "[%s] %s%s", "PASS" if condition else "FAIL", name,
        f"  {detail}" if detail is not None else "",
    )


class ProbeHandler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send_head(self) -> io.BytesIO:
        body = json.dumps({"path": self.path, "source": "sdk-driver"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        return io.BytesIO(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def start_upstream() -> tuple[http.server.ThreadingHTTPServer, int]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ProbeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, int(server.server_address[1])


def wait_url(url: str, expected: bytes, attempts: int = 30) -> bytes:
    last: Exception | None = None
    context = None
    if url.startswith("https://"):
        # This isolated AIO probe uses a self-signed Edge certificate.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=5, context=context) as response:
                body = response.read()
            if expected in body:
                return body
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(1)
    raise RuntimeError(f"URL did not become ready: {url}: {last}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    os.environ.setdefault("YR_TLS", "0")
    os.environ.setdefault("YR_GATEWAY_TLS", "0")
    # The Frontend instance-summary endpoint parses tenant identity even when the
    # isolated AIO does not run IAM signature validation.  Use a syntactically
    # valid, non-production JWT for tenant "default" so lifecycle APIs exercise
    # their real authentication boundary instead of relying on a placeholder.
    os.environ.setdefault(
        "YR_TOKEN",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiJkZWZhdWx0IiwiZXhwIjo5ODc2NTQzMjEwLCJyb2xlIjoiZGV2ZWxvcGVyIn0."
        "aio-e2e-signature",
    )
    os.environ.setdefault("YR_RESUME_MIN_SIZE", str(1024 * 1024))
    os.environ.setdefault("YR_RESUME_CHUNK_SIZE", str(512 * 1024))
    os.environ.setdefault("YR_TUNNEL_CONNECT_TIMEOUT", "60")

    image = os.environ.get("YR_SANDBOX_IMAGE", "yr-gateway-sdk-runtime:e2e")
    result_path = Path(os.environ.get("YR_E2E_RESULT", "/tmp/sdk-result.json"))
    upstream, upstream_port = start_upstream()
    sandbox: Sandbox | None = None
    try:
        nodes = resources()
        check("resources", len(nodes) >= 3, [node.id for node in nodes])
        sandbox = Sandbox(
            image=image,
            runtime="runc",
            cpu=500,
            memory=512,
            idle_timeout=300,
            schedule_timeout=120,
            create_timeout=180,
            name=f"gateway-sdk-{int(time.time())}",
            cwd="/tmp",
            port_forwardings=[18082],
            upstream=f"127.0.0.1:{upstream_port}",
        )
        DETAILS["sandbox_id"] = sandbox.id
        check("sandbox create", bool(sandbox.id), sandbox.id)
        summary: dict[str, object] = {}
        summary_error = ""
        for _ in range(30):
            try:
                info = sandbox.get_info()
            except Exception as exc:  # noqa: BLE001
                summary = {}
                summary_error = repr(exc)
            else:
                summary = asdict(info)
                summary_error = ""
            if summary.get("state") == "running":
                break
            time.sleep(0.2)
        running_detail: dict[str, object] = {"summary": summary}
        if summary_error:
            running_detail["error"] = summary_error
        check(
            "sandbox running",
            summary.get("state") == "running",
            running_detail,
        )

        written = sandbox.files.write("/tmp/sdk.txt", b"sdk-bytes")
        check("files.write", written.size == 9, written.size)
        check("files.read", sandbox.files.read("/tmp/sdk.txt", format="bytes") == b"sdk-bytes")
        check("files.exists", sandbox.files.exists("/tmp/sdk.txt"))
        check("files.make_dir", sandbox.files.make_dir("/tmp/sdk-dir/nested"))
        check("files.list", any(entry.name == "sdk.txt" for entry in sandbox.files.list("/tmp")))
        check("files.stat", sandbox.files.get_info("/tmp/sdk.txt").size == 9)
        check("files.rename", sandbox.files.rename("/tmp/sdk.txt", "/tmp/sdk-renamed.txt").name == "sdk-renamed.txt")
        sandbox.files.remove("/tmp/sdk-renamed.txt")
        check("files.remove", not sandbox.files.exists("/tmp/sdk-renamed.txt"))

        with tempfile.TemporaryDirectory(prefix="yr-sdk-e2e-") as temp:
            root = Path(temp)
            small = root / "small.bin"
            small.write_bytes(bytes(range(256)) * 16)
            sandbox.files.copy_from_local(str(small), "/tmp/small.bin")
            small_out = root / "small.out"
            sandbox.files.copy_to_local("/tmp/small.bin", str(small_out))
            check("copy file small upload/download", small.read_bytes() == small_out.read_bytes())

            large = root / "large.bin"
            large.write_bytes((b"gateway-resumable-copy\x00\xff" * 140000)[: 3 * 1024 * 1024])
            expected_hash = hashlib.sha256(large.read_bytes()).hexdigest()
            sandbox.files.copy_from_local(str(large), "/tmp/large.bin")
            large_out = root / "large.out"
            sandbox.files.copy_to_local("/tmp/large.bin", str(large_out))
            actual_hash = hashlib.sha256(large_out.read_bytes()).hexdigest()
            check("copy file resumable upload/download", expected_hash == actual_hash, actual_hash)

            local_dir = root / "tree"
            local_dir.mkdir()
            (local_dir / "a.txt").write_text("alpha", encoding="utf-8")
            (local_dir / "nested").mkdir()
            (local_dir / "nested" / "b.bin").write_bytes(b"beta\x00")
            sandbox.files.copy_from_local(str(local_dir), "/tmp/uploaded-tree")
            tree_out = root / "tree-out"
            sandbox.files.copy_to_local("/tmp/uploaded-tree", str(tree_out))
            check(
                "copy directory tar upload/download",
                (tree_out / "a.txt").read_text(encoding="utf-8") == "alpha"
                and (tree_out / "nested" / "b.bin").read_bytes() == b"beta\x00",
            )

        command = sandbox.commands.run("printf command-ok; printf command-err >&2; exit 7")
        check("commands.run", command.exit_code == 7 and command.stdout == "command-ok", command.exit_code)
        handle = sandbox.commands.run("cat", background=True, stdin=True)
        handle.send_stdin("stdin-ok\n", eof=True)
        background = handle.wait(timeout=30)
        check("commands background/stdin", background.exit_code == 0 and "stdin-ok" in background.stdout)

        async def shell_case() -> tuple[str, str]:
            shell = await sandbox.shells.create(cwd="/tmp")
            await shell.run("export SDK_E2E=stateful")
            state = await shell.run("printf $SDK_E2E")
            cwd = await shell.run("pwd")
            await shell.kill()
            return state.stdout, cwd.stdout

        shell_state, shell_cwd = asyncio.run(shell_case())
        check(
            "persistent shell",
            shell_state == "stateful" and shell_cwd == "/tmp",
            {"state": shell_state, "cwd": shell_cwd},
        )

        pty_data: list[bytes] = []
        try:
            with sandbox.pty.create(
                ["/bin/sh", "-lc", "printf pty-ok"], on_data=pty_data.append, timeout=60
            ) as session:
                pty_exit = session.wait(timeout=60)
            check("PTY websocket", pty_exit == 0 and b"pty-ok" in b"".join(pty_data))
        except Exception as exc:  # noqa: BLE001
            check("PTY websocket", False, repr(exc))

        try:
            tunnel = sandbox.commands.run(
                "python3 -c 'import sys, urllib.request; "
                "sys.stdout.write(urllib.request.urlopen("
                "\"http://127.0.0.1:8766/tunnel-probe\", timeout=20).read().decode())'",
                timeout=30,
            )
            check(
                "reverse tunnel via Rust gateway",
                tunnel.exit_code == 0 and "sdk-driver" in tunnel.stdout and "tunnel-probe" in tunnel.stdout,
                {"exit_code": tunnel.exit_code, "stdout": tunnel.stdout, "stderr": tunnel.stderr},
            )
        except Exception as exc:  # noqa: BLE001
            check("reverse tunnel via Rust gateway", False, repr(exc))

        try:
            server = sandbox.commands.run(
                "python3 -c 'import http.server; "
                "http.server.ThreadingHTTPServer((\"0.0.0.0\",18082), "
                "http.server.SimpleHTTPRequestHandler).serve_forever()'",
                background=True,
            )
            check("port server start", server.pid > 0, server.pid)
            port_body = wait_url(sandbox.get_port_url(18082), b"Directory listing")
            check("port forwarding via Rust gateway", b"Directory listing" in port_body)
        except Exception as exc:  # noqa: BLE001
            check("port forwarding via Rust gateway", False, repr(exc))
    except Exception as exc:  # noqa: BLE001
        check("unexpected exception", False, repr(exc))
    finally:
        if sandbox is not None:
            sandbox_id = sandbox.id
            try:
                sandbox.kill()
                check("sandbox kill", not sandbox.is_running(), sandbox_id)
            except Exception as exc:  # noqa: BLE001
                check("sandbox kill", False, repr(exc))
        upstream.shutdown()
        upstream.server_close()
        payload = {"passed": PASSED, "failed": FAILED, "details": DETAILS}
        result_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if FAILED:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
