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
    def test_initial_route_delay_logs_one_final_warning_not_every_retry(self):
        """Startup failures warn once after start timeout, not on every retry."""
        tunnel_client = _load_tunnel_client_module()

        class FailingConnect:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                raise ConnectionRefusedError("simulated route delay")

            async def __aexit__(self, *args):
                return False

        client = tunnel_client.TunnelClient(
            upstream="http://127.0.0.1:28800",
            ping_interval=30.0,
            reconnect_base_delay=0.01,
            reconnect_max_delay=0.01,
        )
        with patch.object(tunnel_client.websockets, "connect", FailingConnect), \
             patch.object(tunnel_client.random, "random", return_value=0), \
             patch.object(tunnel_client, "logger") as mock_logger:
            connected = client.start("ws://127.0.0.1:28765", timeout=0.05)
            time.sleep(0.03)
            client.stop()

        final_warning = (
            "Tunnel connection failed after %.1fs: %s; reconnecting in background"
        )
        warning_templates = [call.args[0] for call in mock_logger.warning.call_args_list]
        self.assertEqual(warning_templates.count(final_warning), 1)
        self.assertNotIn("Tunnel disconnected (%s), reconnecting...", warning_templates)
        self.assertFalse(connected)


if __name__ == "__main__":
    unittest.main()
