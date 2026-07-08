import base64
import importlib.util
import pathlib
import ssl
import sys
import types
import unittest
from unittest.mock import patch

from websockets.uri import parse_proxy, parse_uri
import websockets.asyncio.client as ws_client


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


def _proxy_authorization_from_request(request: bytes) -> str:
    for line in request.decode("latin1").split("\r\n"):
        if line.lower().startswith("proxy-authorization:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("Proxy-Authorization header not found")


class TestTunnelClientProxy(unittest.TestCase):
    def test_wss_with_default_ssl_verify_does_not_pass_ssl_none(self):
        tunnel_client = _load_tunnel_client_module()
        client = tunnel_client.TunnelClient(upstream="http://127.0.0.1:28800")
        client._tunnel_url = "wss://127.0.0.1:28765"

        kwargs = client._build_ws_kwargs()

        self.assertNotIn("ssl", kwargs)
        self.assertEqual(kwargs["max_size"], tunnel_client.MAX_TUNNEL_FRAME_SIZE)

    def test_wss_with_ssl_verify_disabled_passes_ssl_context(self):
        tunnel_client = _load_tunnel_client_module()
        with patch.dict("os.environ", {"TUNNEL_SSL_VERIFY": "0"}):
            client = tunnel_client.TunnelClient(upstream="http://127.0.0.1:28800")
        client._tunnel_url = "wss://127.0.0.1:28765"

        kwargs = client._build_ws_kwargs()

        self.assertIsInstance(kwargs["ssl"], ssl.SSLContext)
        self.assertEqual(kwargs["ssl"].verify_mode, ssl.CERT_NONE)

    def test_proxy_auth_unquotes_url_encoded_credentials(self):
        tunnel_client = _load_tunnel_client_module()
        original_prepare = ws_client.prepare_connect_request
        try:
            tunnel_client._patch_websockets_proxy_auth_unquote()
            request = ws_client.prepare_connect_request(
                parse_proxy("http://z00826700:huawei%40123@proxy.example:8080"),
                parse_uri("wss://124.70.166.142:443/tunnel"),
            )
        finally:
            ws_client.prepare_connect_request = original_prepare

        auth = _proxy_authorization_from_request(request)
        decoded = base64.b64decode(auth.split(None, 1)[1]).decode()
        self.assertEqual(decoded, "z00826700:huawei@123")

    def test_proxy_enabled_patches_auth_and_sets_proxy_true(self):
        tunnel_client = _load_tunnel_client_module()
        original_prepare = ws_client.prepare_connect_request
        try:
            with patch.dict("os.environ", {"YR_ENABLE_HTTP_PROXY": "true"}):
                client = tunnel_client.TunnelClient(upstream="http://127.0.0.1:28800")
                client._tunnel_url = "ws://127.0.0.1:28765"
                kwargs = client._build_ws_kwargs()

            self.assertIs(kwargs["proxy"], True)
            self.assertTrue(
                getattr(ws_client.prepare_connect_request, "_yr_proxy_auth_unquote", False)
            )
        finally:
            ws_client.prepare_connect_request = original_prepare

    def test_proxy_disabled_ignores_proxy_environment(self):
        tunnel_client = _load_tunnel_client_module()
        original_prepare = ws_client.prepare_connect_request
        if getattr(original_prepare, "_yr_proxy_auth_unquote", False):
            self.skipTest("websockets proxy auth was already patched globally")
        try:
            with patch.dict(
                "os.environ",
                {
                    "https_proxy": "http://user:pass@proxy.example:8080",
                    "wss_proxy": "http://user:pass@proxy.example:8080",
                },
                clear=True,
            ):
                client = tunnel_client.TunnelClient(upstream="http://127.0.0.1:28800")
                client._tunnel_url = "wss://127.0.0.1:28765"
                kwargs = client._build_ws_kwargs()

            self.assertIsNone(kwargs["proxy"])
            self.assertFalse(
                getattr(ws_client.prepare_connect_request, "_yr_proxy_auth_unquote", False)
            )
        finally:
            ws_client.prepare_connect_request = original_prepare


if __name__ == "__main__":
    unittest.main()
