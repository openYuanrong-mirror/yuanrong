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

"""Tunnel keepalive + reconnection stress test.

Exercises:
1. Sustained concurrent HTTP traffic with heartbeat running
2. Repeated server kill/restart cycles under load
3. Rapid connect/disconnect bursts
4. WS relay under sustained load
5. Heartbeat under high message volume

Usage:
    python -m yr.tests.benchmark_tunnel
    python -m yr.tests.benchmark_tunnel --duration 30 --requests 5000
"""
import argparse
import asyncio
import json
import logging
import resource
import sys
import time
import traceback
from dataclasses import dataclass, field

import aiohttp
from aiohttp import web
import websockets

from yr.sandbox.tunnel_server import TunnelServer
from yr.sandbox.tunnel_client import TunnelClient

# Use ports that don't conflict with unit tests
WS_PORT = 48765
HTTP_PORT = 48766
UPSTREAM_PORT = 48800

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bench")


# Results tracking

@dataclass
class BenchResult:
    name: str
    duration_s: float = 0.0
    total_requests: int = 0
    success_count: int = 0
    error_count: int = 0
    timeout_count: int = 0
    reconnect_count: int = 0
    pings_sent: int = 0
    pongs_received: int = 0
    errors: list = field(default_factory=list)

    @property
    def rps(self) -> float:
        return self.total_requests / self.duration_s if self.duration_s > 0 else 0

    @property
    def success_rate(self) -> float:
        return self.success_count / self.total_requests if self.total_requests > 0 else 0

    def report(self) -> str:
        lines = [
            f"\n{'='*60}",
            f"  {self.name}",
            f"{'='*60}",
            f"  Duration:       {self.duration_s:.1f}s",
            f"  Total requests: {self.total_requests}",
            f"  Successes:      {self.success_count}",
            f"  Errors:         {self.error_count}",
            f"  Timeouts:       {self.timeout_count}",
            f"  Reconnects:     {self.reconnect_count}",
            f"  Pings sent:     {self.pings_sent}",
            f"  Pongs received: {self.pongs_received}",
            f"  RPS:            {self.rps:.1f}",
            f"  Success rate:   {self.success_rate:.1%}",
        ]
        if self.errors:
            lines.append(f"  Sample errors:")
            for e in self.errors[:5]:
                lines.append(f"    - {e}")
        return "\n".join(lines)


# Infrastructure helpers

async def start_upstream(handler=None) -> web.AppRunner:
    """Start a mock upstream HTTP server."""
    if handler is None:
        async def handler(request):
            return web.Response(status=200, body=b"ok")
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", UPSTREAM_PORT).start()
    return runner


async def start_server() -> TunnelServer:
    server = TunnelServer(ws_port=WS_PORT, http_port=HTTP_PORT)
    await server.start()
    return server


def start_client(**kwargs) -> TunnelClient:
    defaults = dict(
        ping_interval=2.0,
        ping_timeout=1.0,
        reconnect_base_delay=0.3,
        reconnect_max_delay=2.0,
    )
    defaults.update(kwargs)
    client = TunnelClient(upstream=f"http://127.0.0.1:{UPSTREAM_PORT}", **defaults)
    client.start(f"ws://127.0.0.1:{WS_PORT}")
    return client


async def wait_connected(client, timeout=5):
    """Wait until client has connected (poll _main_task)."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        loop = getattr(client, "_loop")
        main_task = getattr(client, "_main_task")
        if loop and main_task and not main_task.done():
            return True
        await asyncio.sleep(0.05)
    raise TimeoutError("Client did not connect")


# Benchmarks

async def bench_sustained_http(result: BenchResult, concurrency: int, total: int):
    """1. Sustained concurrent HTTP requests with heartbeat."""
    logger.info("=== bench_sustained_http: concurrency=%d total=%d ===", concurrency, total)
    t0 = time.monotonic()

    upstream_runner = await start_upstream()
    server = await start_server()
    client = start_client()
    await asyncio.sleep(0.8)

    sem = asyncio.Semaphore(concurrency)
    success = 0
    errors = 0
    timeouts = 0
    sample_errors = []

    async def _request(session, idx):
        nonlocal success, errors, timeouts
        async with sem:
            try:
                async with session.get(
                    f"http://127.0.0.1:{HTTP_PORT}/bench/{idx}",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        success += 1
                    else:
                        errors += 1
                        if len(sample_errors) < 5:
                            sample_errors.append(f"HTTP {resp.status}")
            except asyncio.TimeoutError:
                timeouts += 1
            except Exception as e:
                errors += 1
                if len(sample_errors) < 5:
                    sample_errors.append(str(e))

    async with aiohttp.ClientSession() as session:
        tasks = [_request(session, i) for i in range(total)]
        await asyncio.gather(*tasks)

    result.total_requests = total
    result.success_count = success
    result.error_count = errors
    result.timeout_count = timeouts
    result.errors = sample_errors
    result.duration_s = time.monotonic() - t0

    client.stop()
    await server.stop()
    await upstream_runner.cleanup()
    logger.info("  done: %d/%d success in %.1fs (%.0f rps)",
                success, total, result.duration_s, result.rps)


async def bench_reconnect_under_load(result: BenchResult, total: int, kill_count: int):
    """2. Server kill/restart cycles while sending requests."""
    logger.info("=== bench_reconnect_under_load: total=%d kills=%d ===", total, kill_count)
    t0 = time.monotonic()

    upstream_runner = await start_upstream()
    server = await start_server()
    client = start_client()
    await asyncio.sleep(0.8)

    success = 0
    errors = 0
    timeouts = 0
    reconnects = 0
    sample_errors = []
    stop_flag = asyncio.Event()
    request_idx = 0

    async def _sender():
        nonlocal request_idx, success, errors, timeouts
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8)
        ) as session:
            while not stop_flag.is_set():
                request_idx += 1
                try:
                    async with session.get(
                        f"http://127.0.0.1:{HTTP_PORT}/bench/{request_idx}"
                    ) as resp:
                        if resp.status == 200:
                            success += 1
                        else:
                            errors += 1
                except (asyncio.TimeoutError, aiohttp.ClientError, ConnectionError) as e:
                    errors += 1
                    if len(sample_errors) < 10:
                        sample_errors.append(f"req#{request_idx}: {e}")
                await asyncio.sleep(0.01)  # ~100 rps

    sender_task = asyncio.create_task(_sender())

    # Kill and restart server multiple times
    for i in range(kill_count):
        await asyncio.sleep(1.5)
        logger.info("  kill cycle %d/%d", i + 1, kill_count)
        await server.stop()
        reconnects += 1
        await asyncio.sleep(2.0)  # let client detect failure and start reconnecting
        server = await start_server()
        await asyncio.sleep(2.0)  # let client reconnect

    stop_flag.set()
    await sender_task

    result.total_requests = request_idx
    result.success_count = success
    result.error_count = errors
    result.timeout_count = timeouts
    result.reconnect_count = reconnects
    result.errors = sample_errors
    result.duration_s = time.monotonic() - t0

    client.stop()
    await server.stop()
    await upstream_runner.cleanup()
    logger.info("  done: %d reqs, %d success, %d kills in %.1fs",
                request_idx, success, kill_count, result.duration_s)


async def bench_rapid_connect_disconnect(result: BenchResult, cycles: int):
    """3. Rapid client connect/disconnect cycles."""
    logger.info("=== bench_rapid_connect_disconnect: cycles=%d ===", cycles)
    t0 = time.monotonic()

    upstream_runner = await start_upstream()
    server = await start_server()

    success = 0
    errors = 0
    for i in range(cycles):
        client = start_client(
            ping_interval=100,  # no heartbeat interference
            reconnect_base_delay=0.1,
            reconnect_max_delay=0.5,
        )
        await asyncio.sleep(0.3)
        # Try a quick request
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=3)
            ) as session:
                async with session.get(f"http://127.0.0.1:{HTTP_PORT}/quick/{i}") as resp:
                    if resp.status == 200:
                        success += 1
                    else:
                        errors += 1
        except (aiohttp.ClientError, asyncio.TimeoutError):
            errors += 1
        client.stop()
        await asyncio.sleep(0.1)

    result.total_requests = cycles
    result.success_count = success
    result.error_count = errors
    result.duration_s = time.monotonic() - t0

    await server.stop()
    await upstream_runner.cleanup()
    logger.info("  done: %d/%d cycles succeeded in %.1fs",
                success, cycles, result.duration_s)


async def bench_ws_sustained(result: BenchResult, num_clients: int, messages_per_client: int):
    """4. Sustained WS relay under load."""
    logger.info("=== bench_ws_sustained: clients=%d msgs/client=%d ===",
                num_clients, messages_per_client)
    t0 = time.monotonic()

    async def ws_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                await ws.send_str(f"echo:{msg.data}")
        return ws

    upstream_runner = await start_upstream(ws_handler)
    server = await start_server()
    client = start_client()
    await asyncio.sleep(0.8)

    success = 0
    errors = 0
    sample_errors = []

    async def _ws_client(idx):
        nonlocal success, errors
        try:
            async with websockets.connect(f"ws://127.0.0.1:{HTTP_PORT}/ws") as ws:
                for j in range(messages_per_client):
                    payload = f"c{idx}-m{j}"
                    await ws.send(payload)
                    reply = await asyncio.wait_for(ws.recv(), timeout=5)
                    expected = f"echo:{payload}"
                    if reply == expected:
                        success += 1
                    else:
                        errors += 1
        except Exception as e:
            errors += messages_per_client
            if len(sample_errors) < 5:
                sample_errors.append(f"client{idx}: {e}")

    clients = [_ws_client(i) for i in range(num_clients)]
    await asyncio.gather(*clients)

    result.total_requests = num_clients * messages_per_client
    result.success_count = success
    result.error_count = errors
    result.errors = sample_errors
    result.duration_s = time.monotonic() - t0

    client.stop()
    await server.stop()
    await upstream_runner.cleanup()
    logger.info("  done: %d/%d echoed in %.1fs (%.0f msg/s)",
                success, result.total_requests, result.duration_s,
                result.total_requests / result.duration_s if result.duration_s > 0 else 0)


async def bench_heartbeat_under_load(result: BenchResult, duration_s: float):
    """5. Heartbeat correctness under sustained traffic for a fixed duration."""
    logger.info("=== bench_heartbeat_under_load: duration=%.0fs ===", duration_s)
    t0 = time.monotonic()

    upstream_runner = await start_upstream()
    server = await start_server()
    # Fast heartbeat: ping every 1s
    client = start_client(ping_interval=1.0, ping_timeout=0.5)
    await asyncio.sleep(0.8)

    http_success = 0
    http_errors = 0
    stop_flag = asyncio.Event()

    async def _sender():
        nonlocal http_success, http_errors
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5)
        ) as session:
            while not stop_flag.is_set():
                try:
                    async with session.get(
                        f"http://127.0.0.1:{HTTP_PORT}/hb"
                    ) as resp:
                        if resp.status == 200:
                            http_success += 1
                        else:
                            http_errors += 1
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    http_errors += 1
                await asyncio.sleep(0.05)  # ~20 rps

    sender_task = asyncio.create_task(_sender())

    # Run for the specified duration
    await asyncio.sleep(duration_s)
    stop_flag.set()
    await sender_task

    result.total_requests = http_success + http_errors
    result.success_count = http_success
    result.error_count = http_errors
    result.duration_s = time.monotonic() - t0

    client.stop()
    await server.stop()
    await upstream_runner.cleanup()
    logger.info("  done: %d http success, %d errors in %.1fs (heartbeat @ 1s interval)",
                http_success, http_errors, result.duration_s)


# Main

async def run_all(args):
    results = []

    # 1. Sustained HTTP
    r = BenchResult(name="Sustained Concurrent HTTP + Heartbeat")
    await bench_sustained_http(r, concurrency=args.concurrency, total=args.requests)
    results.append(r)

    # 2. Reconnect under load
    r = BenchResult(name="Reconnection Under Load (server kill/restart)")
    await bench_reconnect_under_load(r, total=args.requests, kill_count=args.kill_count)
    results.append(r)

    # 3. Rapid connect/disconnect
    r = BenchResult(name="Rapid Connect/Disconnect Cycles")
    await bench_rapid_connect_disconnect(r, cycles=args.cycles)
    results.append(r)

    # 4. WS sustained
    r = BenchResult(name="Sustained WebSocket Relay")
    await bench_ws_sustained(r, num_clients=args.ws_clients, messages_per_client=args.ws_messages)
    results.append(r)

    # 5. Heartbeat under load
    r = BenchResult(name="Heartbeat Under Sustained Traffic")
    await bench_heartbeat_under_load(r, duration_s=args.duration)
    results.append(r)

    # Summary
    logger.info("%s", "\n" + "=" * 60)
    logger.info("  STRESS TEST SUMMARY")
    logger.info("%s", "=" * 60)
    total_req = 0
    total_ok = 0
    total_err = 0
    for r in results:
        logger.info("%s", r.report())
        total_req += r.total_requests
        total_ok += r.success_count
        total_err += r.error_count
    logger.info("%s", f"\n{'='*60}")
    logger.info("  TOTAL: %d requests, %d success, %d errors",
                total_req, total_ok, total_err)
    success_rate = f"  Overall success rate: {total_ok/total_req*100:.1f}%" if total_req > 0 else "N/A"
    logger.info("%s", success_rate)
    logger.info("%s", "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Tunnel keepalive stress test")
    parser.add_argument("--duration", type=float, default=10, help="Per-bench duration (s)")
    parser.add_argument("--requests", type=int, default=2000, help="HTTP requests for sustained test")
    parser.add_argument("--concurrency", type=int, default=50, help="Concurrent HTTP connections")
    parser.add_argument("--kill-count", type=int, default=3, help="Server kill/restart cycles")
    parser.add_argument("--cycles", type=int, default=20, help="Rapid connect/disconnect cycles")
    parser.add_argument("--ws-clients", type=int, default=10, help="Concurrent WS clients")
    parser.add_argument("--ws-messages", type=int, default=100, help="Messages per WS client")
    args = parser.parse_args()

    # Memory baseline
    mem_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    t0 = time.time()
    asyncio.run(run_all(args))
    elapsed = time.time() - t0

    mem_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    logger.info("\n  Total wall time: %.1fs", elapsed)
    logger.info("  Memory delta: %.1f MB", (mem_after - mem_before) / 1024)


if __name__ == "__main__":
    main()
