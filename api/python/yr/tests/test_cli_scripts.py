#!/usr/bin/env python3
import ast
import importlib.util
import io
from pathlib import Path
import sys
import types
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock
import unittest


class TestCliScripts(unittest.TestCase):
    def load_cli_scripts_with_stubbed_deps(self):
        scripts_path = Path(__file__).resolve().parents[1] / "cli" / "scripts.py"
        spec = importlib.util.spec_from_file_location("yr_cli_scripts_for_test", scripts_path)
        scripts = importlib.util.module_from_spec(spec)

        fake_click = types.ModuleType("click")
        fake_click.option = lambda *args, **kwargs: lambda func: func
        fake_click.argument = lambda *args, **kwargs: lambda func: func
        fake_click.version_option = lambda *args, **kwargs: lambda func: func
        fake_click.pass_context = lambda func: func
        fake_click.Choice = lambda *args, **kwargs: str

        def group_decorator(*args, **kwargs):
            def decorate(func):
                func.command = lambda *a, **kw: lambda command_func: command_func
                func.group = group_decorator
                return func

            return decorate

        fake_click.group = group_decorator

        fake_requests = types.ModuleType("requests")
        fake_requests.Session = object
        fake_requests_exceptions = types.ModuleType("requests.exceptions")
        fake_requests_exceptions.RequestException = Exception
        fake_requests.exceptions = fake_requests_exceptions

        fake_yr = types.ModuleType("yr")
        fake_yr_cli = types.ModuleType("yr.cli")
        fake_yr_cli_exec = types.ModuleType("yr.cli.exec")
        fake_yr_cli_exec.copy_from_remote = lambda *args, **kwargs: None
        fake_yr_cli_exec.copy_to_remote = lambda *args, **kwargs: None
        fake_yr_cli_exec.run_client = lambda *args, **kwargs: None

        with mock.patch.dict(
            sys.modules,
            {
                "click": fake_click,
                "requests": fake_requests,
                "requests.exceptions": fake_requests_exceptions,
                "yr": fake_yr,
                "yr.cli": fake_yr_cli,
                "yr.cli.exec": fake_yr_cli_exec,
            },
        ):
            spec.loader.exec_module(scripts)
        return scripts

    def test_cli_defines_insecure_option_once(self):
        scripts_path = Path(__file__).resolve().parents[1] / "cli" / "scripts.py"
        module = ast.parse(scripts_path.read_text())

        cli_func = next(
            node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "cli"
        )

        insecure_option_count = 0
        for decorator in cli_func.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue
            if decorator.func.attr != "option":
                continue
            if any(isinstance(arg, ast.Constant) and arg.value == "--insecure" for arg in decorator.args):
                insecure_option_count += 1

        self.assertEqual(insecure_option_count, 1)

    def test_sandbox_create_options_are_optional_and_default_to_py310(self):
        scripts_path = Path(__file__).resolve().parents[1] / "cli" / "scripts.py"
        module = ast.parse(scripts_path.read_text())

        sandbox_create_func = next(
            node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "sandbox_create"
        )

        option_required_values = {}
        runtime_default = None
        for decorator in sandbox_create_func.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue
            if decorator.func.attr != "option" or not decorator.args:
                continue
            option_name = decorator.args[0]
            if not isinstance(option_name, ast.Constant) or option_name.value not in {"--namespace", "--name", "--runtime"}:
                continue
            required = next((keyword for keyword in decorator.keywords if keyword.arg == "required"), None)
            option_required_values[option_name.value] = required.value.value
            default = next((keyword for keyword in decorator.keywords if keyword.arg == "default"), None)
            if option_name.value == "--runtime":
                runtime_default = default.value.id

        self.assertEqual(option_required_values, {"--namespace": False, "--name": False, "--runtime": False})
        self.assertEqual(runtime_default, "DEFAULT_SANDBOX_RUNTIME")

    def test_query_instances_appends_pagination_params(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")

        class FakeHTTPClient:
            def __init__(self, **kwargs):
                pass

            def request(self, url, data, method="POST", headers=None):
                self.__class__.url = url
                self.__class__.method = method
                return {"success": True, "data": []}

        with mock.patch.object(scripts, "HTTPClient", FakeHTTPClient):
            ret, resp = scripts.query_instances("tenant-a", page=2, page_size=50)

        self.assertTrue(ret)
        self.assertEqual(resp, [])
        self.assertEqual(FakeHTTPClient.method, "GET")
        self.assertIn("tenant_id=tenant-a", FakeHTTPClient.url)
        self.assertIn("page=2", FakeHTTPClient.url)
        self.assertIn("page_size=50", FakeHTTPClient.url)

    def test_query_instance_uses_frontend_instances_query_endpoint(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")

        class FakeHTTPClient:
            def __init__(self, **kwargs):
                pass

            def request(self, url, data, method="POST", headers=None):
                self.__class__.url = url
                self.__class__.method = method
                return {
                    "success": True,
                    "data": [{"id": "instance-a", "tenantID": "tenant-a"}],
                }

        with mock.patch.object(scripts, "HTTPClient", FakeHTTPClient):
            ret, resp = scripts.query_instance("instance-a", "tenant-a")

        self.assertTrue(ret)
        self.assertEqual(resp["id"], "instance-a")
        self.assertEqual(FakeHTTPClient.method, "GET")
        self.assertIn("/api/instances?", FakeHTTPClient.url)
        self.assertIn("tenant_id=tenant-a", FakeHTTPClient.url)
        self.assertIn("instance_id=instance-a", FakeHTTPClient.url)

    def test_query_instance_ignores_malformed_instance_entries(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")

        class FakeHTTPClient:
            def __init__(self, **kwargs):
                pass

            def request(self, url, data, method="POST", headers=None):
                return {
                    "success": True,
                    "data": {"instances": [None, "bad-entry", {"id": "instance-a", "tenantID": "tenant-a"}]},
                }

        with mock.patch.object(scripts, "HTTPClient", FakeHTTPClient):
            ret, resp = scripts.query_instance("instance-a", "tenant-a")

        self.assertTrue(ret)
        self.assertEqual(resp["id"], "instance-a")

    def test_query_instance_rejects_malformed_response(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")

        class FakeHTTPClient:
            def __init__(self, **kwargs):
                pass

            def request(self, url, data, method="POST", headers=None):
                return {
                    "success": True,
                    "data": {"error": "unexpected response"},
                }

        with mock.patch.object(scripts, "HTTPClient", FakeHTTPClient):
            ret, resp = scripts.query_instance("instance-a", "tenant-a")

        self.assertFalse(ret)
        self.assertEqual(resp["error"], "invalid instances response: missing instances")

    def test_list_instances_passes_pagination_params(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__user", "tenant-a")
        calls = []

        def fake_query_instances(user=None, page=None, page_size=None):
            calls.append((user, page, page_size))
            return True, {"instances": [{"id": "instance-a", "tenantID": "tenant-a"}]}

        with mock.patch.object(scripts, "query_instances", fake_query_instances), redirect_stdout(io.StringIO()):
            scripts.list(3, 25, "instance")

        self.assertEqual(calls, [("tenant-a", 3, 25)])

    def test_list_instances_rejects_oversized_page_size(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()

        with self.assertRaises(SystemExit) as ctx, redirect_stdout(io.StringIO()) as output:
            scripts.list(None, scripts.QUERY_INSTANCES_MAX_PAGE_SIZE + 1, "instance")

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("less than or equal to 1000", output.getvalue())

    def test_list_instances_rejects_oversized_page(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()

        with self.assertRaises(SystemExit) as ctx, redirect_stdout(io.StringIO()) as output:
            scripts.list(scripts.QUERY_INSTANCES_MAX_PAGE + 1, None, "instance")

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("less than or equal to 10000", output.getvalue())

    def test_list_instances_rejects_malformed_response(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__user", "tenant-a")

        def fake_query_instances(user=None, page=None, page_size=None):
            return True, {"error": "unexpected response"}

        with (
            mock.patch.object(scripts, "query_instances", fake_query_instances),
            self.assertRaises(SystemExit) as ctx,
            redirect_stdout(io.StringIO()) as output,
        ):
            scripts.list(None, None, "instance")

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("invalid instances response: missing instances", output.getvalue())

    def test_sandbox_create_uses_default_namespace_and_generates_missing_name(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")
        setattr(scripts, "__user", "tenant-a")

        class FakeUUID:
            def __init__(self, value):
                self.hex = value

        create_calls = []

        def fake_create_sandbox_auto(namespace, name, runtime, image=None, ports=None, upstream=None, proxy_port=8766):
            create_calls.append((namespace, name, runtime, image, ports, upstream, proxy_port))
            return f"{namespace}-{name}", None

        with (
            mock.patch.object(scripts, "create_sandbox_auto", fake_create_sandbox_auto),
            mock.patch.object(scripts.uuid, "uuid4", return_value=FakeUUID("name-id")) as uuid4_mock,
            redirect_stdout(io.StringIO()) as output,
        ):
            scripts.sandbox_create(None, None, scripts.DEFAULT_SANDBOX_RUNTIME)

        self.assertEqual(
            create_calls,
            [(scripts.DEFAULT_SANDBOX_NAMESPACE, "name-id", scripts.DEFAULT_SANDBOX_RUNTIME, None, (), None, 8766)],
        )
        self.assertIn("sandbox created, instance_id=default-name-id", output.getvalue())
        uuid4_mock.assert_called_once_with()

    def test_sandbox_create_preserves_explicit_namespace_and_name(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")

        create_calls = []

        def fake_create_sandbox_auto(namespace, name, runtime, image=None, ports=None, upstream=None, proxy_port=8766):
            create_calls.append((namespace, name, runtime, image, ports, upstream, proxy_port))
            return f"{namespace}-{name}", None

        with (
            mock.patch.object(scripts, "create_sandbox_auto", fake_create_sandbox_auto),
            mock.patch.object(scripts.uuid, "uuid4") as uuid4_mock,
            redirect_stdout(io.StringIO()),
        ):
            scripts.sandbox_create("custom-ns", "custom-name", scripts.DEFAULT_SANDBOX_RUNTIME)

        self.assertEqual(create_calls, [("custom-ns", "custom-name", scripts.DEFAULT_SANDBOX_RUNTIME, None, (), None, 8766)])
        uuid4_mock.assert_not_called()

    def test_sandbox_create_passes_custom_image_to_create_flow(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")
        create_calls = []

        def fake_create_sandbox_auto(namespace, name, runtime, image=None, ports=None, upstream=None, proxy_port=8766):
            create_calls.append((namespace, name, runtime, image, ports, upstream, proxy_port))
            return f"{namespace}-{name}", None

        with (
            mock.patch.object(scripts, "create_sandbox_auto", fake_create_sandbox_auto),
            redirect_stdout(io.StringIO()),
        ):
            scripts.sandbox_create("custom-ns", "custom-name", scripts.DEFAULT_SANDBOX_RUNTIME, "python:3.12-slim")

        self.assertEqual(
            create_calls,
            [("custom-ns", "custom-name", scripts.DEFAULT_SANDBOX_RUNTIME, "python:3.12-slim", (), None, 8766)],
        )

    def test_sandbox_create_passes_ports_and_tunnel_to_create_flow(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")
        create_calls = []

        def fake_create_sandbox_auto(namespace, name, runtime, image=None, ports=None, upstream=None, proxy_port=8766):
            create_calls.append((namespace, name, runtime, image, ports, upstream, proxy_port))
            return f"{namespace}-{name}", None

        with (
            mock.patch.object(scripts, "create_sandbox_auto", fake_create_sandbox_auto),
            redirect_stdout(io.StringIO()),
        ):
            scripts.sandbox_create(
                "custom-ns",
                "custom-name",
                scripts.DEFAULT_SANDBOX_RUNTIME,
                None,
                ("8080", "udp:9090"),
                "127.0.0.1:8000",
                9000,
            )

        self.assertEqual(
            create_calls,
            [
                (
                    "custom-ns",
                    "custom-name",
                    scripts.DEFAULT_SANDBOX_RUNTIME,
                    None,
                    ("8080", "udp:9090"),
                    "127.0.0.1:8000",
                    9000,
                )
            ],
        )

    def test_sandbox_create_rejects_invalid_proxy_port_upper_bound(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")

        with (
            mock.patch.object(scripts, "create_sandbox_auto") as create_sandbox_auto,
            self.assertRaises(SystemExit) as ctx,
            redirect_stdout(io.StringIO()) as output,
        ):
            scripts.sandbox_create(
                "custom-ns",
                "custom-name",
                scripts.DEFAULT_SANDBOX_RUNTIME,
                None,
                (),
                "127.0.0.1:8000",
                65536,
            )

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("--proxy-port must be in [2, 65535]", output.getvalue())
        create_sandbox_auto.assert_not_called()

    def test_sandbox_runtime_function_id_uses_py310_suffix(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()

        self.assertEqual(
            scripts.sandbox_runtime_function_id("python3.10", "default"),
            "sn:cn:yrk:default:function:0-defaultservice-py310:$latest",
        )

    def test_create_sandbox_via_sdk_returns_create_instance_id_without_get(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example:443")
        setattr(scripts, "__jwt_token", "token")

        class FakeConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
                self.auth_token = ""
                self.tenant_id = ""
                self.enable_tls = None

        class FakeInvokeOptions:
            def __init__(self):
                self.custom_extensions = {}

        class FakePortForwarding:
            def __init__(self, port, protocol="TCP"):
                self.port = port
                self.protocol = protocol

        fake_sandbox_instance = mock.Mock()
        fake_sandbox_instance.instance_id = "default-name-id"
        fake_sandbox_instance.real_id = "real-instance-id"
        fake_creator = mock.Mock()
        fake_creator.invoke.return_value = fake_sandbox_instance
        fake_options = mock.Mock(return_value=fake_creator)
        fake_sandbox_instance_class = mock.Mock()
        fake_sandbox_instance_class.options = fake_options
        fake_yr = mock.Mock()
        fake_yr.Config = FakeConfig
        fake_yr.InvokeOptions = FakeInvokeOptions
        fake_yr.PortForwarding = FakePortForwarding
        fake_yr.sandbox.SandboxInstance = fake_sandbox_instance_class

        with (
            mock.patch.object(scripts, "yr", fake_yr),
            mock.patch.object(scripts, "print_sandbox_port_forwarding_urls") as print_urls,
            mock.patch.object(scripts, "resolve_created_sandbox_instance_id", return_value="real-instance-id") as resolve_id,
        ):
            instance_id, tunnel_info = scripts.create_sandbox_via_sdk(
                "default",
                "name-id",
                scripts.DEFAULT_SANDBOX_RUNTIME,
                image="python:3.12-slim",
                ports=("8080", "udp:9090"),
            )

        self.assertEqual(instance_id, "real-instance-id")
        self.assertIsNone(tunnel_info)
        invoke_opt = fake_options.call_args.args[0]
        self.assertEqual(
            scripts.json.loads(invoke_opt.custom_extensions["rootfs"]),
            {"runtime": "runsc", "type": "image", "imageurl": "python:3.12-slim"},
        )
        self.assertEqual(
            [(pf.port, pf.protocol) for pf in invoke_opt.port_forwardings],
            [(8080, "TCP"), (9090, "UDP")],
        )
        self.assertEqual(
            scripts.json.loads(invoke_opt.custom_extensions["network"]),
            {
                "portForwardings": [
                    {"port": 8080, "protocol": "TCP"},
                    {"port": 9090, "protocol": "UDP"},
                ]
            },
        )
        print_urls.assert_called_once_with("real-instance-id", invoke_opt.port_forwardings)
        fake_yr.get.assert_not_called()
        resolve_id.assert_called_once_with("default", "name-id", "real-instance-id")
        fake_yr.init.assert_called_once()
        fake_yr.finalize.assert_called_once()

    def test_create_sandbox_auto_prefers_sdk_create(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")

        with (
            mock.patch.object(scripts, "create_sandbox_via_sdk", return_value=("sdk-real-id", None)) as sdk_create,
            mock.patch.object(scripts, "create_sandbox_via_frontend") as frontend_create,
            mock.patch.object(scripts, "query_instance", return_value=(True, {"id": "actual-sdk-id"})),
        ):
            instance_id, data = scripts.create_sandbox_auto("default", "box", scripts.DEFAULT_SANDBOX_RUNTIME)

        self.assertEqual(instance_id, "actual-sdk-id")
        self.assertIsNone(data)
        sdk_create.assert_called_once_with(
            "default",
            "box",
            "python3.10",
            image=None,
            ports=None,
            upstream=None,
            proxy_port=8766,
        )
        frontend_create.assert_not_called()

    def test_create_sandbox_auto_uses_frontend_api_when_sdk_is_unsupported(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")
        setattr(scripts, "__user", "tenant-a")
        encoded = scripts.base64.b64encode(
            scripts.json.dumps({"instance_id": "tenant-a-box"}).encode()
        ).decode()

        class FakeHTTPClient:
            def __init__(self, **kwargs):
                self.__class__.kwargs = kwargs

            def request(self, url, data, method="POST", headers=None):
                self.__class__.url = url
                self.__class__.data = data
                self.__class__.headers = headers
                self.__class__.method = method
                return {"success": True, "data": {"data": encoded}}

        with (
            mock.patch.object(scripts, "HTTPClient", FakeHTTPClient),
            mock.patch.object(scripts, "create_sandbox_via_sdk", side_effect=RuntimeError("function not found: 0-defaultservice-py310")) as sdk_create,
            mock.patch.object(
                scripts,
                "query_instance",
                return_value=(
                    True,
                    {"id": "actual-tenant-a-box", "function": "default/0-defaultservice-py310/$latest", "status": "running"},
                ),
            ),
        ):
            instance_id, data = scripts.create_sandbox_auto(
                "tenant-a",
                "box",
                scripts.DEFAULT_SANDBOX_RUNTIME,
                image="python:3.12-slim",
            )

        self.assertEqual(instance_id, "actual-tenant-a-box")
        self.assertIsNone(data)
        self.assertEqual(FakeHTTPClient.url, "http://frontend.example/api/sandbox/create")
        self.assertEqual(
            FakeHTTPClient.data,
            {
                "name": "box",
                "namespace": "tenant-a",
                "runtime": "python3.10",
                "rootfs": "python:3.12-slim",
            },
        )
        self.assertEqual(FakeHTTPClient.headers, {"X-Tenant-ID": "tenant-a"})
        self.assertEqual(FakeHTTPClient.method, "POST")
        sdk_create.assert_called_once_with(
            "tenant-a",
            "box",
            "python3.10",
            image="python:3.12-slim",
            ports=None,
            upstream=None,
            proxy_port=8766,
        )

    def test_create_sandbox_via_frontend_passes_ports(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")
        setattr(scripts, "__user", "tenant-a")
        encoded = scripts.base64.b64encode(
            scripts.json.dumps({"instance_id": "tenant-a-box"}).encode()
        ).decode()

        class FakeHTTPClient:
            def __init__(self, **kwargs):
                pass

            def request(self, url, data, method="POST", headers=None):
                self.__class__.data = data
                return {"success": True, "data": {"data": encoded}}

        with mock.patch.object(scripts, "HTTPClient", FakeHTTPClient):
            supported, instance_id, data = scripts.create_sandbox_via_frontend(
                "tenant-a",
                "box",
                scripts.DEFAULT_SANDBOX_RUNTIME,
                ports=("8080", "udp:9090"),
            )

        self.assertTrue(supported)
        self.assertEqual(instance_id, "tenant-a-box")
        self.assertEqual(data, {"data": encoded})
        self.assertEqual(
            FakeHTTPClient.data,
            {"name": "box", "namespace": "tenant-a", "runtime": "python3.10", "ports": ["8080", "udp:9090"]},
        )

    def test_create_sandbox_auto_does_not_fallback_for_duplicate_sdk_error(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")

        with (
            mock.patch.object(scripts, "create_sandbox_via_sdk", side_effect=RuntimeError("same instance id already exists")),
            mock.patch.object(scripts, "create_sandbox_via_frontend") as frontend_create,
            self.assertRaisesRegex(RuntimeError, "same instance id"),
        ):
            scripts.create_sandbox_auto("default", "box", scripts.DEFAULT_SANDBOX_RUNTIME)

        frontend_create.assert_not_called()

    def test_create_sandbox_auto_rejects_old_py39_frontend_fallback(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")

        class FakeHTTPClient:
            def __init__(self, **kwargs):
                pass

            def request(self, url, data, method="POST", headers=None):
                return {
                    "success": False,
                    "status_code": 500,
                    "error": "Executable path of python3.9 is not found",
                }

        with (
            mock.patch.object(scripts, "HTTPClient", FakeHTTPClient),
            mock.patch.object(scripts, "create_sandbox_via_sdk", side_effect=RuntimeError("function not found: 0-defaultservice-py310")) as sdk_create,
            mock.patch.object(scripts, "query_instance", return_value=(True, {"id": "default-box"})),
            self.assertRaisesRegex(RuntimeError, "Executable path of python3.9"),
        ):
            scripts.create_sandbox_auto("default", "box", scripts.DEFAULT_SANDBOX_RUNTIME)

        sdk_create.assert_called_once_with(
            "default",
            "box",
            "python3.10",
            image=None,
            ports=None,
            upstream=None,
            proxy_port=8766,
        )

    def test_sandbox_list_prints_header_and_status(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__user", "tenant-a")

        def fake_query_instances(user=None):
            return True, {
                "instances": [
                    {"id": "tenant-a-box", "tenantID": "tenant-a", "status": "running"},
                    {"id": "app-not-sandbox", "tenantID": "tenant-a", "status": "running"},
                ]
            }

        with mock.patch.object(scripts, "query_instances", fake_query_instances), redirect_stdout(io.StringIO()) as output:
            scripts.sandbox_list(None)

        self.assertEqual(
            output.getvalue().splitlines(),
            ["INSTANCE_ID   TENANT_ID  STATUS", "tenant-a-box  tenant-a   running"],
        )

    def test_delete_sandbox_via_sdk_uses_async_terminate(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        runtime = mock.Mock()
        scripts.yr.init = mock.Mock()
        scripts.yr.finalize = mock.Mock()
        scripts.yr.kill_instance = mock.Mock()
        scripts.yr.runtime_holder = types.SimpleNamespace(
            global_runtime=types.SimpleNamespace(get_runtime=lambda: runtime)
        )

        with (
            mock.patch.object(scripts, "build_sandbox_sdk_config", return_value=object()) as build_config,
            mock.patch.object(scripts.yr, "init") as yr_init,
            mock.patch.object(scripts.yr, "finalize") as yr_finalize,
        ):
            scripts.delete_sandbox_via_sdk("sandbox-id")

        build_config.assert_called_once_with(scripts.DEFAULT_SANDBOX_RUNTIME)
        yr_init.assert_called_once()
        runtime.terminate_instance.assert_called_once_with("sandbox-id")
        scripts.yr.kill_instance.assert_not_called()
        yr_finalize.assert_called_once()

    def test_sandbox_delete_uses_sdk_first(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")

        with (
            mock.patch.object(scripts, "delete_sandbox_via_sdk") as sdk_delete,
            mock.patch.object(scripts, "wait_until_sandbox_deleted", return_value=True),
            mock.patch.object(scripts, "HTTPClient") as http_client,
            redirect_stdout(io.StringIO()) as output,
        ):
            scripts.sandbox_delete("sandbox-id")

        sdk_delete.assert_called_once_with("sandbox-id")
        http_client.assert_not_called()
        self.assertIn("succeed to delete sandbox: sandbox-id", output.getvalue())

    def test_sandbox_delete_falls_back_to_frontend_and_passes_tls_options(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")
        setattr(scripts, "__insecure", True)
        setattr(scripts, "__jwt_token", "token")

        class FakeHTTPClient:
            def __init__(self, **kwargs):
                self.__class__.kwargs = kwargs

            def request(self, url, data, method="POST", headers=None):
                self.__class__.url = url
                self.__class__.method = method
                return {"success": True, "data": {}}

        with (
            mock.patch.object(scripts, "HTTPClient", FakeHTTPClient),
            mock.patch.object(scripts, "delete_sandbox_via_sdk", side_effect=RuntimeError("sdk delete failed")),
            mock.patch.object(scripts, "wait_until_sandbox_deleted", return_value=True),
            redirect_stdout(io.StringIO()),
        ):
            scripts.sandbox_delete("sandbox-id")

        self.assertEqual(FakeHTTPClient.url, "http://frontend.example/api/sandbox/sandbox-id")
        self.assertEqual(FakeHTTPClient.method, "DELETE")
        self.assertTrue(FakeHTTPClient.kwargs["insecure"])
        self.assertEqual(FakeHTTPClient.kwargs["jwt_token"], "token")

    def test_sandbox_delete_uses_frontend_when_sdk_delete_leaves_instance(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "frontend.example")

        class FakeHTTPClient:
            def __init__(self, **kwargs):
                pass

            def request(self, url, data, method="POST", headers=None):
                return {"success": True, "data": {}}

        with (
            mock.patch.object(scripts, "HTTPClient", FakeHTTPClient),
            mock.patch.object(scripts, "wait_until_sandbox_deleted", side_effect=[False, True]),
            mock.patch.object(scripts, "delete_sandbox_via_sdk") as sdk_delete,
            redirect_stdout(io.StringIO()) as output,
        ):
            scripts.sandbox_delete("sandbox-id")

        sdk_delete.assert_called_once_with("sandbox-id")
        self.assertIn("succeed to delete sandbox: sandbox-id", output.getvalue())

    def test_wait_until_sandbox_deleted_polls_until_missing(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        clock = mock.Mock()
        clock.time.side_effect = [0, 1, 1]

        with (
            mock.patch.object(scripts, "sandbox_exists", side_effect=[True, False]),
            mock.patch.object(scripts, "time", clock),
        ):
            self.assertTrue(scripts.wait_until_sandbox_deleted("sandbox-id", timeout=30))

        clock.sleep.assert_called_once_with(1)

    def test_exec_uses_wss_for_443_token_only_connection(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "124.70.166.142:443")
        setattr(scripts, "__client_cert", None)
        setattr(scripts, "__client_key", None)
        setattr(scripts, "__ca_cert", None)
        setattr(scripts, "__insecure", True)
        setattr(scripts, "__jwt_token", "token")
        captured = {}

        async def fake_run_client(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        with mock.patch.object(scripts, "run_client", fake_run_client):
            scripts.exec(False, False, True, "instance-id", "bash")

        self.assertEqual(captured["args"][:2], ("124.70.166.142", "443"))
        self.assertTrue(captured["kwargs"]["use_ssl"])
        self.assertFalse(captured["kwargs"]["verify_server"])
        self.assertIsNone(captured["kwargs"]["cert_file"])
        self.assertIsNone(captured["kwargs"]["key_file"])
        self.assertEqual(captured["kwargs"]["token"], "token")
        self.assertTrue(captured["kwargs"]["quiet"])

    def test_exec_keeps_tty_mode_verbose(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "124.70.166.142:443")
        setattr(scripts, "__client_cert", None)
        setattr(scripts, "__client_key", None)
        setattr(scripts, "__ca_cert", None)
        setattr(scripts, "__insecure", True)
        captured = {}

        async def fake_run_client(*args, **kwargs):
            captured["kwargs"] = kwargs

        with mock.patch.object(scripts, "run_client", fake_run_client):
            scripts.exec(False, True, True, "instance-id", "bash")

        self.assertFalse(captured["kwargs"]["quiet"])

    def test_exec_without_tty_suppresses_keyboard_interrupt_message(self):
        scripts = self.load_cli_scripts_with_stubbed_deps()
        setattr(scripts, "__server_address", "124.70.166.142:443")
        setattr(scripts, "__client_cert", None)
        setattr(scripts, "__client_key", None)
        setattr(scripts, "__ca_cert", None)
        setattr(scripts, "__insecure", True)
        stderr = io.StringIO()

        async def fake_run_client(*args, **kwargs):
            raise KeyboardInterrupt()

        with mock.patch.object(scripts, "run_client", fake_run_client), redirect_stderr(stderr):
            scripts.exec(False, False, True, "instance-id", "bash")

        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
