#!/usr/bin/env python3
# coding=UTF-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2026. All rights reserved.
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

"""Off-cluster (云外) smoke tests for openyuanrong SDK.

These tests exercise the core SDK APIs against a remote YuanRong cluster
from outside the cluster using TLS + in_cluster=False (off-cluster / 云外).

Run:
    export YR_SERVER_ADDRESS=<ip:port>
    export YR_JWT_TOKEN=<jwt_token>   # optional
    /path/to/python3.9 -m pytest -s -vv -p no:conftest test_off_cluster.py

    # or via the wrapper script:
    bash run_off_cluster_test.sh -a <ip:port>
"""

import os
import json
import subprocess
import sys
import time
import pytest
import yr

pytestmark = pytest.mark.off_cluster
YRCLI_SANDBOX_CREATE_TIMEOUT = 240


def _get_addr():
    addr = os.getenv("YR_SERVER_ADDRESS", "")
    if not addr:
        raise ValueError("YR_SERVER_ADDRESS not set")
    return addr


def _get_jwt_token():
    return os.getenv("YR_JWT_TOKEN", "")


def _get_enable_tls():
    return os.getenv("YR_ENABLE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}


def _get_yrcli_command():
    return [sys.executable, "-m", "yr.cli.scripts"]


def _get_faas_runtime():
    return os.getenv(
        "YR_OFF_CLUSTER_FAAS_RUNTIME",
        f"python{sys.version_info.major}.{sys.version_info.minor}",
    )


def _unique_name(prefix):
    return f"{prefix}-{os.getpid()}-{int(time.time() * 1000)}"


def _build_conf():
    addr = _get_addr()
    return yr.Config(
        server_address=addr,
        ds_address=addr,
        in_cluster=False,
        enable_tls=_get_enable_tls(),
        log_level=os.getenv("YR_LOG_LEVEL", "DEBUG"),
        auth_token=_get_jwt_token(),
    )


@pytest.fixture(scope="session")
def init_yr():
    """Session-scoped yr init for off-cluster (云外) mode."""
    conf = _build_conf()
    yr.init(conf)
    yield
    yr.finalize()


@pytest.fixture(scope="session")
def require_remote_python_runtime(init_yr):
    """Skip worker-executed tests when the remote cluster lacks a compatible Python runtime."""

    @yr.invoke
    def _probe():
        return "remote-python-ready"

    try:
        assert yr.get(_probe.invoke(), timeout=60) == "remote-python-ready"
    except RuntimeError as exc:
        message = str(exc)
        if "Executable path of python" in message and "is not found on" in message:
            pytest.skip(f"off-cluster: remote worker Python runtime unavailable: {message}")
        raise


@pytest.fixture(scope="session")
def require_plain_http_for_yrcli():
    if _get_enable_tls():
        pytest.skip("yrcli off-cluster smoke requires YR_ENABLE_TLS=false")


def _run_yrcli(*args, timeout=120, user=None):
    command = [
        *_get_yrcli_command(),
        "--server-address",
        _get_addr(),
    ]
    if user is not None:
        command.extend(["--user", user])
    token = _get_jwt_token()
    if token:
        command.extend(["--jwt-token", token])
    command.extend(args)
    env = os.environ.copy()
    if not _get_enable_tls():
        env.pop("YR_INSECURE", None)
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        env=env,
    )
    assert result.returncode == 0, (
        f"yrcli {' '.join(args)} failed with {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return result


def _ensure_faas_runtime(runtime):
    deployed = _run_yrcli(
        "deploy-language-rt",
        "--runtime",
        runtime,
        "--no-rootfs",
        timeout=180,
    )
    assert (
        "Successfully deployed FaaS language runtime function" in deployed.stdout
        or "Successfully updated FaaS language runtime function" in deployed.stdout
    )


# ============================================================
# 1. Object Store (put / get)
# ============================================================

@pytest.mark.smoke
def test_put_get_string(init_yr):
    ref = yr.put("hello off-cluster")
    assert yr.get(ref) == "hello off-cluster"


@pytest.mark.smoke
def test_put_get_int(init_yr):
    ref = yr.put(42)
    assert yr.get(ref) == 42


@pytest.mark.smoke
def test_put_get_dict(init_yr):
    data = {"name": "openyuanrong", "version": 1, "active": True}
    ref = yr.put(data)
    assert yr.get(ref) == data


@pytest.mark.smoke
def test_put_get_list(init_yr):
    data = [1, "two", 3.0, None, True]
    ref = yr.put(data)
    assert yr.get(ref) == data


@pytest.mark.smoke
def test_put_get_bytes(init_yr):
    data = b"\x00\x01\x02\xff"
    ref = yr.put(data)
    result = yr.get(ref)
    assert bytes(result) == data


@pytest.mark.smoke
def test_put_get_nested(init_yr):
    data = {"list": [1, 2, {"inner": [True, False]}], "num": 0}
    ref = yr.put(data)
    assert yr.get(ref) == data


@pytest.mark.smoke
def test_put_get_large_bytes(init_yr):
    data = b"A" * (512 * 1024)  # 512 KB
    ref = yr.put(data)
    result = yr.get(ref)
    assert bytes(result) == data


@pytest.mark.smoke
def test_get_empty_list(init_yr):
    assert yr.get([], 30) == []


@pytest.mark.smoke
def test_get_multiple_refs(init_yr):
    refs = [yr.put(i) for i in range(5)]
    assert yr.get(refs) == [0, 1, 2, 3, 4]


# ============================================================
# 2. Stateless Function (yr.invoke)
# ============================================================

@pytest.mark.smoke
def test_invoke_basic(init_yr, require_remote_python_runtime):
    @yr.invoke
    def add(a, b):
        return a + b

    ref = add.invoke(10, 20)
    assert yr.get(ref) == 30


@pytest.mark.smoke
def test_invoke_string(init_yr, require_remote_python_runtime):
    @yr.invoke
    def greet(name):
        return f"hello {name}"

    ref = greet.invoke("openyuanrong")
    assert yr.get(ref) == "hello openyuanrong"
    @yr.invoke
    def dis_sum(args):
        return sum(args)

    ref = dis_sum.invoke([1, 2, 3, 4, 5])
    assert yr.get(ref) == 15


@pytest.mark.smoke
def test_invoke_with_object_ref_arg(init_yr):
    """Pass ObjectRef as argument; runtime should auto-resolve on worker side."""
    @yr.invoke
    def get_nums():
        return [10, 20, 30]

    @yr.invoke
    def dis_sum(args):
        return sum(args)

    nums_ref = get_nums.invoke()
    ref = dis_sum.invoke(nums_ref)
    assert yr.get(ref, timeout=120) == 60


@pytest.mark.smoke
def test_invoke_with_nested_ref(init_yr):
    """Pass nested ObjectRefs inside a list argument."""
    @yr.invoke
    def get_num(x):
        return x

    @yr.invoke
    def dis_sum(args):
        return sum(yr.get(args))

    refs = [get_num.invoke(i) for i in [1, 2, 3]]
    ref = dis_sum.invoke(refs)
    assert yr.get(ref, timeout=120) == 6


@pytest.mark.smoke
def test_invoke_return_multiple_values(init_yr, require_remote_python_runtime):
    @yr.invoke(return_nums=3)
    def func_returns():
        return 1, 2, 3

    ref1, ref2, ref3 = func_returns.invoke()
    assert yr.get([ref1, ref2, ref3]) == [1, 2, 3]


@pytest.mark.smoke
def test_invoke_return_none(init_yr, require_remote_python_runtime):
    @yr.invoke(return_nums=0)
    def func():
        return

    ref = func.invoke()
    assert ref is None


@pytest.mark.smoke
def test_invoke_with_big_bytes(init_yr):
    @yr.invoke
    def echo(x):
        return x

    data = b"X" * (200 * 1024)  # 200 KB
    ref = echo.invoke(data)
    assert yr.get(ref) == data


@pytest.mark.smoke
def test_invoke_redefine(init_yr, require_remote_python_runtime):
    """Decorating a new function with the same name should work."""
    @yr.invoke
    def get_num():
        return 1

    assert yr.get(get_num.invoke()) == 1

    @yr.invoke
    def get_num():
        return 2

    assert yr.get(get_num.invoke()) == 2


@pytest.mark.smoke
def test_invoke_runtime_error(init_yr, require_remote_python_runtime):
    @yr.invoke
    def raise_error():
        raise RuntimeError("test error from off-cluster driver")

    with pytest.raises(RuntimeError):
        yr.get(raise_error.invoke())


# ============================================================
# 3. Stateful Instance (yr.instance)
# ============================================================

@pytest.mark.smoke
def test_instance_basic(init_yr, require_remote_python_runtime):
    @yr.instance
    class Counter:
        def __init__(self):
            self.cnt = 0

        def add(self):
            self.cnt += 1
            return self.cnt

    counter = Counter.invoke()
    assert yr.get(counter.add.invoke()) == 1
    assert yr.get(counter.add.invoke()) == 2
    assert yr.get(counter.add.invoke()) == 3


@pytest.mark.smoke
def test_instance_named(init_yr, require_remote_python_runtime):
    @yr.instance
    class Counter:
        def __init__(self):
            self.cnt = 0

        def add(self):
            self.cnt += 1
            return self.cnt

    opt = yr.InvokeOptions()
    opt.name = f"off-cluster-test-actor-{os.getpid()}-{int(time.time() * 1000)}"
    opt.concurrency = 1
    ins = Counter.options(opt).invoke()
    assert yr.get(ins.add.invoke()) == 1

    # Same named instance should share state
    ins2 = Counter.options(opt).invoke()
    assert yr.get(ins2.add.invoke()) == 2


@pytest.mark.smoke
def test_instance_pass_to_invoke(init_yr):
    """Pass an instance as argument to a stateless function."""
    @yr.instance
    class Counter:
        def __init__(self):
            self.cnt = 0

        def add(self):
            self.cnt += 1
            return self.cnt

    @yr.invoke
    def use_counter(c):
        return yr.get(c.add.invoke()) + yr.get(c.add.invoke())

    counter = Counter.invoke()
    result = yr.get(use_counter.invoke(counter), timeout=120)
    assert result == 3


@pytest.mark.smoke
def test_instance_order_preserve(init_yr, require_remote_python_runtime):
    """Instance method calls should be ordered (single concurrency)."""
    @yr.instance
    class Counter:
        def __init__(self):
            self.cnt = 0

        def add(self):
            self.cnt += 1
            return self.cnt

    opt = yr.InvokeOptions()
    opt.concurrency = 1
    counter = Counter.options(opt).invoke()
    results = [yr.get(counter.add.invoke()) for _ in range(10)]
    assert results == list(range(1, 11))


# ============================================================
# 4. KV Store
# ============================================================

@pytest.mark.smoke
def test_kv_write_read_del(init_yr):
    key = "off-cluster-test-kv-1"
    yr.kv_write(key, b"value1")
    assert yr.kv_read(key) == b"value1"
    yr.kv_del(key)


@pytest.mark.smoke
def test_kv_write_read_del_in_invoke(init_yr, require_remote_python_runtime):
    """Worker writes, reads, and deletes its own KV entries (no cross-network read-back)."""
    @yr.invoke
    def kv_ops():
        yr.kv_write("off-cluster-test-kv-3", b"worker_value")
        v = yr.kv_read("off-cluster-test-kv-3")
        yr.kv_del("off-cluster-test-kv-3")
        return v

    result = yr.get(kv_ops.invoke())
    assert result == b"worker_value"


@pytest.mark.smoke
def test_kv_set_get(init_yr):
    key = "off-cluster-test-kv-setget"
    yr.kv_set(key, b"setget_value")
    assert yr.kv_get(key) == b"setget_value"
    yr.kv_del(key)


# ============================================================
# 5. wait / cancel
# ============================================================

@pytest.mark.smoke
def test_wait_basic(init_yr, require_remote_python_runtime):
    @yr.invoke
    def get_num(x):
        return x

    refs = [get_num.invoke(i) for i in range(5)]
    ready, not_ready = yr.wait(refs, wait_num=5)
    assert len(not_ready) == 0
    assert len(ready) == 5
    assert yr.get(ready) == [0, 1, 2, 3, 4]


@pytest.mark.smoke
def test_wait_with_exception(init_yr, require_remote_python_runtime):
    @yr.invoke
    def may_throw(n):
        if n % 2 == 0:
            raise RuntimeError(f"even number: {n}")
        return n

    ref = may_throw.invoke(0)
    ready, not_ready = yr.wait([ref], wait_num=1, timeout=120)
    assert len(not_ready) == 0
    assert ready == [ref]
    with pytest.raises(RuntimeError):
        yr.get(ref)


@pytest.mark.smoke
def test_cancel(init_yr, require_remote_python_runtime):
    @yr.invoke
    def slow_func(x):
        time.sleep(3)
        return x

    ref = slow_func.invoke("cancelled")
    yr.cancel(ref)
    with pytest.raises(RuntimeError) as exc_info:
        yr.get(ref)
    assert "cancel" in str(exc_info.value).lower()


# ============================================================
# 6. Stability
# ============================================================

@pytest.mark.smoke
def test_repeated_invoke_stability(init_yr, require_remote_python_runtime):
    """Verify repeated invoke/get cycles are stable across the session."""
    @yr.invoke
    def echo(x):
        return x

    for i in range(5):
        assert yr.get(echo.invoke(i)) == i


# ============================================================
# 7. Sandbox and yrcli smoke
# ============================================================

@pytest.mark.smoke
def test_sandbox_create_exec_and_terminate(init_yr):
    sandbox = None
    for attempt in range(2):
        sandbox = yr.sandbox.create(name=_unique_name(f"sdk-sbox-{attempt}"), idle_timeout=600)
        if sandbox is not None:
            break
        time.sleep(5)
    assert sandbox is not None
    try:
        result = sandbox.exec("echo sandbox-ok && pwd", timeout=30)
        assert result["returncode"] == 0
        assert "sandbox-ok" in result["stdout"]
        assert "/tmp/yr_sandbox_" in result["stdout"]
    finally:
        sandbox.terminate()


@pytest.mark.smoke
def test_sandbox_tunnel_http_get_post(init_yr):
    """Tunnel smoke: local upstream + reverse tunnel + GET/POST via sandbox exec.

    Mirrors sandbox_tunnel_http_longrun_stress.py at smoke scale (one GET /ping
    and one POST /echo). Validates the full upstream -> TunnelClient -> sandbox
    path on whichever Python ABI the SDK wheel was built for (e.g. cp313).
    """
    import contextlib
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _UpstreamHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/ping":
                body = b"pong"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length > 0 else b""
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # noqa: A003
            return

    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        probe.bind(("127.0.0.1", 0))
        upstream_port = probe.getsockname()[1]
    upstream = ThreadingHTTPServer(("127.0.0.1", upstream_port), _UpstreamHandler)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    sandbox = None
    try:
        sandbox = yr.sandbox.create(
            name=_unique_name("sdk-tunnel"),
            upstream=f"127.0.0.1:{upstream_port}",
            idle_timeout=600,
        )
        assert sandbox is not None
        tunnel_url = sandbox.get_tunnel_url()
        assert tunnel_url, "empty tunnel url"

        ping = sandbox.exec(f"curl -sS {tunnel_url}/ping", timeout=60)
        assert ping["returncode"] == 0, ping
        assert "pong" in (ping["stdout"] or ""), ping

        payload = 1024
        post_cmd = (
            f"head -c {payload} /dev/zero | tr '\\0' 'x' "
            f"| curl -sS -X POST --data-binary @- {tunnel_url}/echo | wc -c"
        )
        post = sandbox.exec(post_cmd, timeout=60)
        assert post["returncode"] == 0, post
        assert str(payload) in (post["stdout"] or ""), post
    finally:
        if sandbox is not None:
            try:
                sandbox.terminate()
            except Exception:
                pass
        upstream.shutdown()
        upstream.server_close()


@pytest.mark.smoke
def test_yrcli_exec_with_sandbox_instance(require_plain_http_for_yrcli):
    namespace = "offcluster"
    name = _unique_name("yrcli-exec")
    create = _run_yrcli(
        "sandbox", "create", "--namespace", namespace, "--name", name, timeout=YRCLI_SANDBOX_CREATE_TIMEOUT
    )
    marker = "instance_id="
    assert marker in create.stdout
    sandbox_id = create.stdout.split(marker, 1)[1].strip().split()[0]
    try:
        _run_yrcli("exec", sandbox_id, "touch /tmp/yrcli-exec-marker", timeout=60)
        listed = _run_yrcli("exec", sandbox_id, "ls /tmp/yrcli-exec-marker", timeout=60)
        assert "/tmp/yrcli-exec-marker" in listed.stdout
    finally:
        _run_yrcli("sandbox", "delete", sandbox_id)


@pytest.mark.smoke
def test_yrcli_sandbox_detached_lifecycle(require_plain_http_for_yrcli):
    namespace = "offcluster"
    name = _unique_name("yrcli-sandbox")
    create = _run_yrcli(
        "sandbox", "create", "--namespace", namespace, "--name", name, timeout=YRCLI_SANDBOX_CREATE_TIMEOUT
    )
    marker = "instance_id="
    assert marker in create.stdout
    sandbox_id = create.stdout.split(marker, 1)[1].strip().split()[0]
    try:
        listed = _run_yrcli("sandbox", "list", "--namespace", namespace)
        assert sandbox_id in listed.stdout
        queried = _run_yrcli("sandbox", "query", sandbox_id)
        assert sandbox_id in queried.stdout
    finally:
        _run_yrcli("sandbox", "delete", sandbox_id)


@pytest.mark.smoke
def test_yrcli_faas_deploy_query_delete(require_plain_http_for_yrcli, tmp_path):
    namespace = "faaspy"
    function = _unique_name("yrcli-faas").replace("-", "")
    full_name = f"0@{namespace}@{function}"
    runtime = _get_faas_runtime()
    _ensure_faas_runtime(runtime)
    code_dir = tmp_path / "faas"
    code_dir.mkdir()
    handler_path = code_dir / "handler.py"
    handler_path.write_text(
        "import os\n"
        "\n"
        "def handler(event, context):\n"
        "    if isinstance(event, dict):\n"
        "        return {\n"
        "            'ok': True,\n"
        "            'echo': event.get('text', event.get('name', 'unknown')),\n"
        "            'mode': event.get('mode', 'json'),\n"
        "            'function_name': os.environ.get('YR_FUNCTION_NAME', ''),\n"
        "        }\n"
        "    return {'ok': True, 'echo': event, 'mode': 'text'}\n",
        encoding="utf-8",
    )
    assert handler_path.is_file()
    assert handler_path.stat().st_size > 0
    print(f"yrcli faas code_path={code_dir} handler_size={handler_path.stat().st_size}", flush=True)
    function_json = tmp_path / "function.json"
    function_json.write_text(
        json.dumps(
            {
                "name": full_name,
                "runtime": runtime,
                "description": "yrcli off-cluster smoke handler",
                "handler": "handler.handler",
                "kind": "faas",
                "cpu": 300,
                "memory": 128,
                "timeout": 60,
                "customResources": {},
                "environment": {},
                "extendedHandler": {},
                "extendedTimeout": {},
                "minInstance": "0",
                "maxInstance": "1",
                "concurrentNum": "1",
                "storageType": "local",
                "codePath": str(code_dir),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    deployed = _run_yrcli(
        "deploy",
        "--code-path",
        str(code_dir),
        "--function-json",
        str(function_json),
        "--update",
        timeout=180,
    )
    assert "succeed to deploy function" in deployed.stdout or "succeed to update function" in deployed.stdout
    try:
        queried = _run_yrcli("query", "-f", f"{namespace}@{function}")
        assert namespace in queried.stdout
        assert function in queried.stdout
        function_info = json.loads(queried.stdout)
        assert function_info.get("runtime") == runtime
        invoked = _run_yrcli(
            "invoke",
            "-f",
            f"{namespace}@{function}",
            "--payload",
            '{"text": "ping"}',
            "--timeout",
            "120",
            timeout=150,
        )
        assert '"ok": true' in invoked.stdout
        assert '"echo": "ping"' in invoked.stdout
    finally:
        _run_yrcli("delete", "-f", f"{namespace}@{function}", "--no-clear-package")
