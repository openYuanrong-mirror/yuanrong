#!/usr/bin/env python3
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
import asyncio
import importlib.util
import pathlib
import sys
import time
import types
import unittest
from unittest.mock import patch


_TUNNEL_MODULES = (
    "yr",
    "yr.sandbox",
    "yr.sandbox.tunnel_protocol",
    "yr.sandbox.tunnel_client",
)


def _load_tunnel_client_module():
    root = pathlib.Path(__file__).resolve().parents[1] / "sandbox"
    previous_modules = {name: sys.modules.get(name) for name in _TUNNEL_MODULES}
    missing_modules = {name for name in _TUNNEL_MODULES if name not in sys.modules}

    try:
        sys.modules["yr"] = types.ModuleType("yr")
        sys.modules["yr.sandbox"] = types.ModuleType("yr.sandbox")

        for name in ["tunnel_protocol", "tunnel_client"]:
            path = root / f"{name}.py"
            module_name = f"yr.sandbox.{name}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)

        return sys.modules["yr.sandbox.tunnel_client"]
    finally:
        for name in missing_modules:
            sys.modules.pop(name, None)
        for name, module in previous_modules.items():
            if module is not None:
                sys.modules[name] = module


class TestTunnelClientLogging(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tunnel_client = _load_tunnel_client_module()

    def test_initial_route_delay_warns_after_five_consecutive_failures(self):
        """Startup connection failures should warn only after five consecutive failures."""
        class FailingConnect:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                raise ConnectionRefusedError("simulated route delay")

            async def __aexit__(self, *args):
                return False

        client = self.tunnel_client.TunnelClient(
            upstream="http://127.0.0.1:28800",
            ping_interval=30.0,
            reconnect_base_delay=0.01,
            reconnect_max_delay=0.01,
        )
        with patch.object(self.tunnel_client.websockets, "connect", FailingConnect), \
             patch.object(self.tunnel_client.random, "random", return_value=0), \
             patch.object(self.tunnel_client, "logger") as mock_logger:
            connected = client.start("ws://127.0.0.1:28765", timeout=0.01)
            time.sleep(0.35)
            client.stop()

        warning_templates = [call.args[0] for call in mock_logger.warning.call_args_list]
        threshold_warning = (
            "Tunnel connection failed %d consecutive times: %s; reconnecting in background"
        )
        self.assertEqual(warning_templates.count(threshold_warning), 1)
        threshold_warning_call = next(
            call for call in mock_logger.warning.call_args_list
            if call.args[0] == threshold_warning
        )
        self.assertEqual(threshold_warning_call.args[1], 5)
        self.assertIn("simulated route delay", str(threshold_warning_call.args[2]))
        self.assertNotIn("Tunnel disconnected (%s), reconnecting...", warning_templates)
        self.assertFalse(connected)

    def test_recv_loop_clears_connection_failure_count(self):
        """A successfully established recv loop starts a new connection-failure streak."""
        client = self.tunnel_client.TunnelClient(upstream="http://127.0.0.1:28800")
        setattr(client, "_connect_failure_count", 4)
        setattr(client, "_last_connect_error", ConnectionRefusedError("old failure"))

        async def fake_recv_frames(ws, http):
            return None

        async def fake_heartbeat_loop(ws):
            await asyncio.sleep(60)

        setattr(client, "_recv_frames", fake_recv_frames)
        setattr(client, "_heartbeat_loop", fake_heartbeat_loop)

        recv_loop = getattr(client, "_recv_loop")
        asyncio.run(recv_loop(object(), object()))

        self.assertEqual(getattr(client, "_connect_failure_count"), 0)
        self.assertIsNone(getattr(client, "_last_connect_error"))



if __name__ == "__main__":
    unittest.main()
