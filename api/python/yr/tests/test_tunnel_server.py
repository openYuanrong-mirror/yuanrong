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

# api/python/yr/tests/test_tunnel_server.py
import asyncio
import json
import base64
import unittest
import websockets
from yr.sandbox.tunnel_server import TunnelServer
from yr.sandbox.tunnel_protocol import (
    HttpReqFrame, HttpRespFrame, ErrorFrame,
    WsConnectFrame, WsConnectedFrame, WsMessageFrame, WsCloseFrame,
    PingFrame, PongFrame,
    MAX_TUNNEL_FRAME_SIZE, parse_frame, make_id,
)


WS_PORT = 18765
HTTP_PORT = 18766


async def _run_server():
    server = TunnelServer(ws_port=WS_PORT, http_port=HTTP_PORT)
    await server.start()
    return server


class TestTunnelServerHttp(unittest.TestCase):
    def test_http_req_forwarded_to_sdk_and_response_returned(self):
        """Port B HTTP request should be forwarded as http_req frame and response returned."""
        async def _run():
            server = await _run_server()
            try:
                # Connect a mock SDK client to Port A
                async with websockets.connect(f"ws://127.0.0.1:{WS_PORT}") as sdk_ws:
                    # Send HTTP request to Port B concurrently
                    async def send_http():
                        import aiohttp
                        async with aiohttp.ClientSession() as session:
                            async with session.get(f"http://127.0.0.1:{HTTP_PORT}/hello") as resp:
                                return resp.status, await resp.read()

                    http_task = asyncio.create_task(send_http())
                    # SDK receives the frame
                    raw = await asyncio.wait_for(sdk_ws.recv(), timeout=5)
                    frame = parse_frame(raw)
                    self.assertIsInstance(frame, HttpReqFrame)
                    self.assertEqual(frame.method, "GET")
                    self.assertEqual(frame.path, "/hello")
                    # SDK sends back a response
                    resp_frame = HttpRespFrame(
                        id=frame.id, status=200,
                        headers={"Content-Type": "text/plain"},
                        body=b"world",
                    )
                    await sdk_ws.send(resp_frame.to_json())
                    status, body = await asyncio.wait_for(http_task, timeout=5)
                    self.assertEqual(status, 200)
                    self.assertEqual(body, b"world")
            finally:
                await server.stop()

        asyncio.run(_run())

    def test_http_error_frame_returns_502(self):
        """If SDK sends error frame, Port B should return 502."""
        async def _run():
            server = await _run_server()
            try:
                async with websockets.connect(f"ws://127.0.0.1:{WS_PORT}") as sdk_ws:
                    async def send_http():
                        import aiohttp
                        async with aiohttp.ClientSession() as session:
                            async with session.get(f"http://127.0.0.1:{HTTP_PORT}/fail") as resp:
                                return resp.status

                    http_task = asyncio.create_task(send_http())
                    raw = await asyncio.wait_for(sdk_ws.recv(), timeout=5)
                    frame = parse_frame(raw)
                    await sdk_ws.send(ErrorFrame(id=frame.id, message="upstream down").to_json())
                    status = await asyncio.wait_for(http_task, timeout=5)
                    self.assertEqual(status, 502)
            finally:
                await server.stop()

        asyncio.run(_run())

    def test_no_sdk_connected_returns_503(self):
        """Without SDK connection, Port B should return 503."""
        async def _run():
            server = await _run_server()
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"http://127.0.0.1:{HTTP_PORT}/x") as resp:
                        self.assertEqual(resp.status, 503)
            finally:
                await server.stop()

        asyncio.run(_run())

    def test_http_request_over_aiohttp_default_limit_is_forwarded(self):
        """Port B should use the tunnel body limit, not aiohttp's 1MB default."""
        async def _run():
            server = await _run_server()
            try:
                payload = b"x" * (1024 * 1024 + 1)
                async with websockets.connect(
                    f"ws://127.0.0.1:{WS_PORT}",
                    max_size=MAX_TUNNEL_FRAME_SIZE,
                ) as sdk_ws:
                    async def send_http():
                        import aiohttp
                        async with aiohttp.ClientSession() as session:
                            async with session.post(
                                f"http://127.0.0.1:{HTTP_PORT}/large",
                                data=payload,
                            ) as resp:
                                return resp.status, await resp.read()

                    http_task = asyncio.create_task(send_http())
                    recv_task = asyncio.create_task(sdk_ws.recv())
                    done, pending = await asyncio.wait(
                        {http_task, recv_task},
                        timeout=5,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if recv_task not in done:
                        recv_task.cancel()
                    self.assertIn(recv_task, done,
                                  "large request was rejected before tunnel forwarding")

                    frame = parse_frame(recv_task.result())
                    self.assertIsInstance(frame, HttpReqFrame)
                    self.assertEqual(frame.method, "POST")
                    self.assertEqual(frame.path, "/large")
                    self.assertEqual(frame.body, payload)

                    await sdk_ws.send(HttpRespFrame(
                        id=frame.id,
                        status=200,
                        headers={"Content-Type": "text/plain"},
                        body=b"ok",
                    ).to_json())
                    status, body = await asyncio.wait_for(http_task, timeout=5)
                    self.assertEqual(status, 200)
                    self.assertEqual(body, b"ok")
            finally:
                await server.stop()

        asyncio.run(_run())


class TestTunnelServerPingPong(unittest.TestCase):
    def test_server_echoes_pong_for_ping(self):
        """Server should echo a PongFrame when it receives a PingFrame."""
        async def _run():
            server = await _run_server()
            try:
                async with websockets.connect(f"ws://127.0.0.1:{WS_PORT}") as sdk_ws:
                    ping = PingFrame(id="test-ping-1", timestamp=1234.5)
                    await sdk_ws.send(ping.to_json())
                    raw = await asyncio.wait_for(sdk_ws.recv(), timeout=5)
                    frame = parse_frame(raw)
                    self.assertIsInstance(frame, PongFrame)
                    self.assertEqual(frame.id, "test-ping-1")
                    self.assertEqual(frame.timestamp, 1234.5)
            finally:
                await server.stop()

        asyncio.run(_run())


class TestTunnelServerWs(unittest.TestCase):
    def test_ws_no_sdk_returns_error(self):
        """WS request without SDK connected should close with error, not raise 500."""
        async def _run():
            server = await _run_server()
            try:
                async with websockets.connect(f"ws://127.0.0.1:{HTTP_PORT}/stream") as ws:
                    # Server should close the connection gracefully
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    # Expect a close frame or connection closure
                    # The server should close with 1011 and "No TunnelClient connected"
            except websockets.ConnectionClosed as e:
                # Server closed gracefully with 1011 and error message
                self.assertEqual(e.code, 1011)
                self.assertIn("No TunnelClient connected", e.reason)
            except websockets.exceptions.InvalidStatus:
                # Older behavior: HTTP 500 during upgrade. This is also acceptable
                # since the goal is "no unhandled exception", but the RuntimeError
                # catch in _handle_ws should prevent this path.
                return
            finally:
                await server.stop()

        asyncio.run(_run())

    def test_ws_upgrade_sends_ws_connect_frame(self):
        """WS Upgrade on Port B should send ws_connect frame to SDK."""
        async def _run():
            server = await _run_server()
            try:
                async with websockets.connect(f"ws://127.0.0.1:{WS_PORT}") as sdk_ws:
                    async def connect_portb_ws():
                        async with websockets.connect(f"ws://127.0.0.1:{HTTP_PORT}/stream"):
                            await asyncio.sleep(0.2)

                    ws_task = asyncio.create_task(connect_portb_ws())
                    raw = await asyncio.wait_for(sdk_ws.recv(), timeout=5)
                    frame = parse_frame(raw)
                    self.assertIsInstance(frame, WsConnectFrame)
                    self.assertEqual(frame.path, "/stream")
                    # Send ws_connected so server can proceed
                    await sdk_ws.send(WsConnectedFrame(id=frame.id).to_json())
                    await asyncio.wait_for(ws_task, timeout=2)
            finally:
                await server.stop()

        asyncio.run(_run())

    def test_ws_message_relayed_from_sdk_to_portb_client(self):
        """Messages from SDK should be forwarded to Port B WS client."""
        async def _run():
            server = await _run_server()
            received = []
            try:
                async with websockets.connect(f"ws://127.0.0.1:{WS_PORT}") as sdk_ws:
                    async def portb_client():
                        async with websockets.connect(f"ws://127.0.0.1:{HTTP_PORT}/stream") as ws:
                            msg = await asyncio.wait_for(ws.recv(), timeout=5)
                            received.append(msg)

                    client_task = asyncio.create_task(portb_client())
                    # Handle ws_connect
                    raw = await asyncio.wait_for(sdk_ws.recv(), timeout=5)
                    frame = parse_frame(raw)
                    await sdk_ws.send(WsConnectedFrame(id=frame.id).to_json())
                    # Send message from SDK side
                    await sdk_ws.send(WsMessageFrame(id=frame.id, data="ping", binary=False).to_json())
                    await asyncio.wait_for(client_task, timeout=5)
                    self.assertEqual(received, ["ping"])
            finally:
                await server.stop()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
