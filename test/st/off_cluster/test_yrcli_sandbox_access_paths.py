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

"""Off-cluster yrcli sandbox access-path verification.

These cases are intentionally end-to-end: they call the local yrcli against a
running Docker AIO deployment, create real detached sandbox instances, and
verify gateway port forwarding plus reverse tunnel access.
"""

import os
import base64
import re
import shutil
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


pytestmark = [pytest.mark.off_cluster, pytest.mark.smoke]

SANDBOX_CREATE_TIMEOUT = int(os.environ.get("YRCLI_SANDBOX_CREATE_TIMEOUT", "600"))
SANDBOX_EXEC_TIMEOUT = int(os.environ.get("YRCLI_SANDBOX_EXEC_TIMEOUT", "90"))
SANDBOX_NAMESPACE = os.environ.get("YRCLI_SANDBOX_NAMESPACE", "offcluster")
VERIFY_PORT = int(os.environ.get("YRCLI_VERIFY_PORT", "8080"))
VERIFY_IMAGE = os.environ.get("YR_SANDBOX_VERIFY_IMAGE", "aio-yr-runtime:latest").strip()


def _server_address():
    address = os.environ.get("YR_SERVER_ADDRESS", "").strip()
    if not address:
        pytest.skip("YR_SERVER_ADDRESS is required for off-cluster yrcli sandbox verification")
    return address


def _yrcli_command():
    python_bin = os.environ.get("YRCLI_VERIFY_PYTHON_BIN") or sys.executable
    repo_root = os.environ.get("YR_REPO_ROOT")
    if repo_root:
        return [python_bin, "-m", "yr.cli.scripts"]

    sibling = os.path.join(os.path.dirname(python_bin), "yrcli")
    if os.path.exists(sibling):
        return [sibling]
    found = shutil.which("yrcli")
    if found:
        return [found]
    return [python_bin, "-m", "yr.cli.scripts"]


def _yrcli_base_args():
    command = _yrcli_command() + [
        "--server-address",
        _server_address(),
        "--log-level",
        os.environ.get("YRCLI_LOG_LEVEL", "INFO"),
    ]
    if os.environ.get("YR_INSECURE", "").strip().lower() in {"1", "true", "yes", "on"}:
        command.append("--insecure")
    token = os.environ.get("YR_JWT_TOKEN", "").strip()
    if token:
        command.extend(["--jwt-token", token])
    return command


def _base_env():
    env = os.environ.copy()
    repo_root = env.get("YR_REPO_ROOT")
    if repo_root:
        api_python = os.path.join(repo_root, "api", "python")
        env["PYTHONPATH"] = api_python + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.setdefault("YR_ENABLE_TLS", "false")
    env.setdefault("YR_IN_CLUSTER", "false")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def _run_yrcli(*args, timeout=120):
    command = _yrcli_base_args() + list(args)
    result = subprocess.run(
        command,
        env=_base_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, (
        f"yrcli {' '.join(args)} failed with {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return result


def _new_name(prefix):
    return f"{prefix}-{os.getpid()}-{int(time.time() * 1000)}"


def _extract_instance_id(output):
    match = re.search(r"instance_id=([^\s]+)", output)
    assert match, f"cannot find instance_id in output:\n{output}"
    return match.group(1)


def _extract_port_url(output, port):
    match = re.search(rf"port\s+{port}:\s+(\S+)", output)
    assert match, f"cannot find port {port} gateway URL in output:\n{output}"
    return match.group(1)


def _delete_sandbox(instance_id):
    try:
        _run_yrcli("sandbox", "delete", instance_id, timeout=90)
    except Exception as exc:
        print(f"warning: failed to delete sandbox {instance_id}: {exc}", file=sys.stderr)


def _remote_python_http_server_command(port):
    server_code = f"""
import http.server
import pathlib
import socketserver

pathlib.Path('/tmp/yrcli-port-forward-ready').write_text('ready')

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'yrcli-port-forward-ok')

    def log_message(self, *args):
        pass

with socketserver.TCPServer(('0.0.0.0', {port}), Handler) as httpd:
    httpd.serve_forever()
"""
    launcher_code = f"""
import base64
import pathlib
import subprocess
import sys
import time

script = pathlib.Path('/tmp/yrcli_port_forward_server.py')
ready = pathlib.Path('/tmp/yrcli-port-forward-ready')
log = pathlib.Path('/tmp/yrcli-port-forward.log')
ready.unlink(missing_ok=True)
script.write_bytes(base64.b64decode({base64.b64encode(server_code.encode()).decode()!r}))
with log.open('wb') as log_file:
    subprocess.Popen(
        [sys.executable, str(script)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
for _ in range(40):
    if ready.exists():
        print(ready.read_text(), flush=True)
        sys.exit(0)
    time.sleep(0.5)
if log.exists():
    print(log.read_text(), end='')
sys.exit(1)
"""
    return _remote_python_exec_command(launcher_code)


def _remote_http_get_command(url):
    code = (
        "import urllib.request\n"
        f"print(urllib.request.urlopen({url!r}, timeout=15).read().decode())\n"
    )
    return _remote_python_exec_command(code)


def _remote_python_exec_command(code):
    encoded = base64.b64encode(code.encode()).decode()
    return f"python3 -c exec(__import__('base64').b64decode('{encoded}'))"


def _wait_url_contains(url, expected, timeout=60):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                body = response.read().decode()
            if expected in body:
                return
            last_error = f"unexpected body: {body!r}"
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    raise AssertionError(f"URL {url} did not return {expected!r}: {last_error}")


def _exec_until_contains(instance_id, command, expected, timeout=60):
    deadline = time.time() + timeout
    last_output = ""
    last_error = None
    while time.time() < deadline:
        try:
            result = _run_yrcli(
                "exec",
                "-t",
                instance_id,
                command,
                timeout=SANDBOX_EXEC_TIMEOUT,
            )
            last_output = result.stdout
            if expected in result.stdout:
                return result
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    raise AssertionError(
        f"exec output did not contain {expected!r}; "
        f"last_output={last_output!r}; last_error={last_error!r}; "
        f"upstream_requests={_UpstreamHandler.request_count}"
    )


def _free_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _UpstreamHandler(BaseHTTPRequestHandler):
    response_body = b"yrcli-reverse-tunnel-ok"
    request_count = 0

    def do_GET(self):
        type(self).request_count += 1
        self.send_response(200)
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, *args):
        pass


def _start_local_upstream():
    _UpstreamHandler.request_count = 0
    server = ThreadingHTTPServer(("127.0.0.1", _free_local_port()), _UpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _start_tunnel_create(name, upstream):
    command = _yrcli_base_args() + [
        "sandbox",
        "create",
        "--namespace",
        SANDBOX_NAMESPACE,
        "--name",
        name,
        "--upstream",
        upstream,
        "--proxy-port",
        "8766",
    ]
    if VERIFY_IMAGE:
        command.extend(["--image", VERIFY_IMAGE])
    return subprocess.Popen(
        command,
        env=_base_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )


def _wait_for_tunnel_create(proc):
    lines = []
    instance_id = None
    deadline = time.time() + SANDBOX_CREATE_TIMEOUT
    while time.time() < deadline:
        assert proc.stdout is not None
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            time.sleep(0.2)
            continue
        lines.append(line)
        if "instance_id=" in line:
            instance_id = _extract_instance_id(line)
        if "tunnel connected" in line or "tunnel connecting in background" in line:
            assert instance_id, f"tunnel started without instance_id:\n{''.join(lines)}"
            _drain_process_output(proc)
            return instance_id, "".join(lines)
    remaining = proc.stdout.read() if proc.stdout else ""
    raise AssertionError(f"tunnel create did not become ready:\n{''.join(lines)}{remaining}")


def _drain_process_output(proc):
    if proc.stdout is None:
        return

    def _drain():
        for _ in proc.stdout:
            pass

    thread = threading.Thread(target=_drain, daemon=True)
    thread.start()


def _stop_tunnel_process(proc):
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGINT)
        proc.wait(timeout=15)
    except Exception:
        proc.kill()
        proc.wait(timeout=15)


def test_yrcli_sandbox_create_image_and_port_forwarding():
    name = _new_name("yrcli-access")
    instance_id = None
    create_args = [
        "sandbox",
        "create",
        "--namespace",
        SANDBOX_NAMESPACE,
        "--name",
        name,
        "--port",
        str(VERIFY_PORT),
    ]
    if VERIFY_IMAGE:
        create_args.extend(["--image", VERIFY_IMAGE])

    create = _run_yrcli(*create_args, timeout=SANDBOX_CREATE_TIMEOUT)
    instance_id = _extract_instance_id(create.stdout)
    gateway_url = _extract_port_url(create.stdout, VERIFY_PORT)
    try:
        started = _run_yrcli(
            "exec",
            instance_id,
            _remote_python_http_server_command(VERIFY_PORT),
            timeout=SANDBOX_EXEC_TIMEOUT,
        )
        assert started.returncode == 0
        _wait_url_contains(gateway_url, "yrcli-port-forward-ok", timeout=60)
    finally:
        if instance_id:
            _delete_sandbox(instance_id)


def test_yrcli_sandbox_create_reverse_tunnel():
    upstream = _start_local_upstream()
    host, port = upstream.server_address
    name = _new_name("yrcli-tunnel")
    instance_id = None
    proc = None
    try:
        proc = _start_tunnel_create(name, f"{host}:{port}")
        instance_id, output = _wait_for_tunnel_create(proc)
        assert "sandbox upstream proxy: http://127.0.0.1:8766" in output
        assert "tunnel connected" in output
        result = _exec_until_contains(
            instance_id,
            _remote_http_get_command("http://127.0.0.1:8766/"),
            "yrcli-reverse-tunnel-ok",
            timeout=60,
        )
        assert "yrcli-reverse-tunnel-ok" in result.stdout
    finally:
        upstream.shutdown()
        upstream.server_close()
        if proc is not None:
            _stop_tunnel_process(proc)
        if instance_id:
            _delete_sandbox(instance_id)
