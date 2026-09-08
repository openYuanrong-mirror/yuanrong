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

"""Verify that a live Rust data-plane stream participates in sandbox idle lifecycle."""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from yr_sandbox import Sandbox


# Keep machine-readable results on stdout without diagnostic prefixes.
result_logger = logging.getLogger(__name__ + ".result")
result_logger.setLevel(logging.INFO)
result_logger.propagate = False
result_handler = logging.StreamHandler(sys.stdout)
result_handler.setFormatter(logging.Formatter("%(message)s"))
result_logger.addHandler(result_handler)


def wait_running(sandbox: Sandbox, expected: bool, timeout: float) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if sandbox.is_running() is expected:
            return time.monotonic() - started
        time.sleep(0.25)
    raise AssertionError(
        f"sandbox running state did not become {expected} within {timeout}s"
    )


def read_http_headers(stream: socket.socket) -> bytes:
    response = bytearray()
    while b"\r\n\r\n" not in response:
        chunk = stream.recv(4096)
        if not chunk:
            break
        response.extend(chunk)
        if len(response) > 64 * 1024:
            raise AssertionError("CONNECT response headers exceed 64 KiB")
    return bytes(response)


def connect_edge(edge: str, instance_id: str, target_port: int) -> tuple[socket.socket, bytes]:
    edge_host, edge_port = edge.rsplit(":", 1)
    stream = socket.create_connection((edge_host, int(edge_port)), timeout=10)
    authority = f"{instance_id}:{target_port}"
    request = (
        f"CONNECT {authority} HTTP/1.1\r\n"
        f"Host: {authority}\r\n"
        "X-Yr-Access-Kind: port-forwarding\r\n"
        f"X-Request-Id: idle-e2e-{uuid.uuid4()}\r\n"
        "\r\n"
    ).encode("ascii")
    stream.sendall(request)
    response = read_http_headers(stream)
    status_line = response.split(b"\r\n", 1)[0]
    if b" 200 " not in status_line:
        stream.close()
        raise AssertionError(f"Edge CONNECT failed: {response!r}")
    return stream, response


def node_active_streams(endpoints: list[str]) -> tuple[int, dict[str, int]]:
    counts: dict[str, int] = {}
    for endpoint in endpoints:
        with urllib.request.urlopen(f"http://{endpoint}/metrics", timeout=3) as response:
            metrics = response.read().decode("utf-8")
        count = next(
            int(float(line.split()[1]))
            for line in metrics.splitlines()
            if line.startswith("data_plane_node_proxy_active_streams ")
        )
        counts[endpoint] = count
    return sum(counts.values()), counts


def wait_active_stream(endpoints: list[str], timeout: float = 5) -> dict[str, int]:
    started = time.monotonic()
    latest: dict[str, int] = {}
    while time.monotonic() - started < timeout:
        total, latest = node_active_streams(endpoints)
        if total >= 1:
            return latest
        time.sleep(0.1)
    raise AssertionError(f"Node Proxy did not expose an active stream: {latest}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    os.environ.setdefault("YR_TLS", "0")
    os.environ.setdefault("YR_GATEWAY_TLS", "0")
    os.environ.setdefault(
        "YR_TOKEN",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiJkZWZhdWx0IiwiZXhwIjo5ODc2NTQzMjEwLCJyb2xlIjoiZGV2ZWxvcGVyIn0."
        "aio-e2e-signature",
    )

    image = os.environ.get("YR_SANDBOX_IMAGE", "yr-gateway-sdk-runtime:e2e")
    result_path = Path(os.environ.get("YR_E2E_RESULT", "/tmp/idle-timeout-result.json"))
    edge = os.environ.get("YR_GATEWAY_ADDRESS", "10.250.0.20:8080")
    metrics_addresses = os.environ.get(
        "YR_NODE_METRICS", "10.250.0.10:18443,10.250.0.12:18443,10.250.0.13:18443"
    )
    metrics_endpoints = [item.strip() for item in metrics_addresses.split(",") if item.strip()]
    idle_timeout = int(os.environ.get("YR_IDLE_TIMEOUT_SECONDS", "4"))
    hold_seconds = idle_timeout + 4
    target_port = 18083
    sandbox: Sandbox | None = None
    stream: socket.socket | None = None
    result: dict[str, object] = {
        "idle_timeout_seconds": idle_timeout,
        "hold_seconds": hold_seconds,
        "target_port": target_port,
    }
    try:
        sandbox = Sandbox(
            image=image,
            runtime="runc",
            cpu=500,
            memory=512,
            idle_timeout=idle_timeout,
            schedule_timeout=120,
            create_timeout=180,
            name=f"gateway-idle-{int(time.time())}",
            cwd="/tmp",
            port_forwardings=[target_port],
        )
        result["sandbox_id"] = sandbox.id
        wait_running(sandbox, True, 10)

        command = sandbox.commands.run(
            f"nohup python3 -m http.server {target_port} --bind 0.0.0.0 "
            ">/tmp/idle-http.log 2>&1 </dev/null & echo $!",
            timeout=30,
        )
        if command.exit_code != 0 or not command.stdout.strip():
            raise AssertionError(
                f"failed to start detached HTTP server: {command.exit_code} {command.stderr!r}"
            )
        result["server_pid"] = command.stdout.strip()

        # CONNECT uses the gateway route.SanitizeID wire format.
        safe_id = sandbox.id.replace("@", "-at-").translate(str.maketrans("/._", "---"))
        stream, connect_response = connect_edge(edge, safe_id, target_port)
        result["connect_status"] = connect_response.split(b"\r\n", 1)[0].decode(
            "ascii", errors="replace"
        )
        result["active_streams_by_node"] = wait_active_stream(metrics_endpoints)

        hold_started = time.monotonic()
        time.sleep(hold_seconds)
        result["actual_hold_seconds"] = round(time.monotonic() - hold_started, 3)
        if not sandbox.is_running():
            raise AssertionError("sandbox was reclaimed while CONNECT stream remained open")
        result["running_after_hold"] = True

        # Prove the held stream is still functional after the idle timeout,
        # rather than merely observing a stale Node counter.
        stream.sendall(b"GET / HTTP/1.0\r\nHost: sandbox\r\n\r\n")
        response = bytearray()
        while True:
            chunk = stream.recv(8192)
            if not chunk:
                break
            response.extend(chunk)
        if not response.startswith(b"HTTP/1.0 200"):
            raise AssertionError(f"held CONNECT stream stopped relaying: {bytes(response[:200])!r}")
        result["probe_after_hold"] = "HTTP/1.0 200"
        stream.close()
        stream = None

        reclaimed_after = wait_running(sandbox, False, idle_timeout + 20)
        result["reclaimed_after_stream_close_seconds"] = round(reclaimed_after, 3)
        result["reclaimed_after_close"] = True
        logging.info(
            "[PASS] open CONNECT kept sandbox alive for %ss; "
            "sandbox reclaimed %.3fs after stream close",
            hold_seconds,
            reclaimed_after,
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)
        raise
    finally:
        if stream is not None:
            stream.close()
        if sandbox is not None:
            if sandbox.is_running():
                try:
                    sandbox.kill()
                except Exception as exc:  # noqa: BLE001
                    result["cleanup_error"] = repr(exc)
            else:
                sandbox.close()
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        result_logger.info("%s", json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
