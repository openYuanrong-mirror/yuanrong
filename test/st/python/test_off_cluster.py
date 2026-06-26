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
import base64
import json
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, urlunparse
import pytest
import yr

pytestmark = pytest.mark.off_cluster
YRCLI_SANDBOX_CREATE_TIMEOUT = 240
YRCLI_SANDBOX_EXEC_TIMEOUT = 90


def _get_addr():
    addr = os.getenv("YR_SERVER_ADDRESS", "")
    if not addr:
        raise ValueError("YR_SERVER_ADDRESS not set")
    return addr


def _get_jwt_token():
    return os.getenv("YR_JWT_TOKEN", "")


def _get_enable_tls():
    return os.getenv("YR_ENABLE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}


def _get_protocol():
    return "https" if _get_enable_tls() else "http"


def _get_yrcli_command():
    return [sys.executable, "-m", "yr.cli.scripts"]


def _get_faas_runtime():
    return os.getenv(
        "YR_OFF_CLUSTER_FAAS_RUNTIME",
        f"python{sys.version_info.major}.{sys.version_info.minor}",
    )


def _get_faas_tenant_id():
    return os.getenv("YR_OFF_CLUSTER_FAAS_TENANT_ID", "default")


def _unique_name(prefix):
    return f"{prefix}-{os.getpid()}-{int(time.time() * 1000)}"


def _extract_sandbox_id(output):
    marker = "instance_id="
    assert marker in output
    return output.split(marker, 1)[1].strip().split()[0]


def _extract_port_url(output, port):
    marker = f"port {port}:"
    for line in output.splitlines():
        if marker in line:
            return line.split(marker, 1)[1].strip()
    raise AssertionError(f"cannot find port {port} gateway URL in output:\n{output}")


def _gateway_url_candidates(url):
    parsed = urlparse(url)
    candidates = [url]
    host = parsed.hostname

    gateway_addr = os.getenv("YR_GATEWAY_ADDRESS", "").strip()
    if gateway_addr:
        candidates.append(urlunparse(parsed._replace(netloc=gateway_addr)))

    if host and parsed.port == 18888:
        candidates.append(urlunparse(parsed._replace(netloc=f"{host}:8888")))
    elif host and parsed.port == 8888:
        candidates.append(urlunparse(parsed._replace(netloc=f"{host}:18888")))

    return list(dict.fromkeys(candidates))


def _wait_any_url_contains(urls, expected, timeout=60):
    deadline = time.time() + timeout
    last_errors = {}
    while time.time() < deadline:
        for url in urls:
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    body = response.read().decode()
                if expected in body:
                    return url
                last_errors[url] = f"unexpected body: {body!r}"
            except Exception as exc:
                last_errors[url] = repr(exc)
        time.sleep(1)
    raise AssertionError(f"none of {urls} returned {expected!r}: {last_errors}")


def _invoke_faas_short_http(namespace, function, payload, headers=None, timeout=150):
    url = f"{_get_protocol()}://{_get_addr()}/invocations/{_get_faas_tenant_id()}/{namespace}/{function}/"
    request_headers = {
        "Content-Type": "application/json",
    }
    token = _get_jwt_token()
    if token:
        request_headers["X-Auth"] = token
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.getcode(), response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        headers_text = str(exc.headers).strip()
        raise AssertionError(
            f"FaaS short invoke failed: status={exc.code} reason={exc.reason} "
            f"url={url} headers={headers_text!r} body={body!r}"
        ) from exc


def _decode_json_body(body):
    value = json.loads(body)
    if isinstance(value, str):
        value = json.loads(value)
    return value


def _build_session_header(session_id):
    return {
        "X-Instance-Session": json.dumps(
            {
                "sessionID": session_id,
                "sessionTTL": 0,
                "concurrency": 1,
            }
        ),
    }


def _remote_python_exec_command(code):
    encoded = base64.b64encode(code.encode()).decode()
    return f"python3 -c exec(__import__('base64').b64decode('{encoded}'))"


def _remote_python_http_server_command(port):
    code = f"""
import http.server
import pathlib
import socketserver
import subprocess
import sys
import textwrap
import time

script = pathlib.Path('/tmp/yrcli_port_forward_server.py')
ready = pathlib.Path('/tmp/yrcli-port-forward-ready')
log = pathlib.Path('/tmp/yrcli-port-forward.log')
ready.unlink(missing_ok=True)
script.write_text(textwrap.dedent('''
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
'''))
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
    return _remote_python_exec_command(code)


def _remote_http_get_command(url):
    code = (
        "import urllib.request\n"
        f"print(urllib.request.urlopen({url!r}, timeout=15).read().decode())\n"
    )
    return _remote_python_exec_command(code)


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
    command = [
        *_get_yrcli_command(),
        "--server-address",
        _get_addr(),
        "sandbox",
        "create",
        "--namespace",
        "offcluster",
        "--name",
        name,
        "--upstream",
        upstream,
        "--proxy-port",
        "8766",
    ]
    token = _get_jwt_token()
    if token:
        command[3:3] = ["--jwt-token", token]
    env = os.environ.copy()
    if not _get_enable_tls():
        env.pop("YR_INSECURE", None)
    return subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )


def _wait_for_tunnel_create(proc):
    lines = []
    instance_id = None
    deadline = time.time() + YRCLI_SANDBOX_CREATE_TIMEOUT
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
            instance_id = _extract_sandbox_id(line)
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
                timeout=YRCLI_SANDBOX_EXEC_TIMEOUT,
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
        env.pop("YR_VERIFY_FILE", None)
        env.pop("YR_CERT_FILE", None)
        env.pop("YR_PRIVATE_KEY_FILE", None)
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


@pytest.mark.smoke
def test_get_allow_partial_timeout(init_yr, require_remote_python_runtime):
    @yr.invoke
    def slow_value():
        time.sleep(3)
        return "slow"

    fast_ref = yr.put("fast")
    slow_ref = slow_value.invoke()
    assert yr.get([fast_ref, slow_ref], timeout=1, allow_partial=True) == ["fast", None]
    assert yr.get(slow_ref, timeout=120) == "slow"


@pytest.mark.smoke
def test_serialization_common_python_types(init_yr, require_remote_python_runtime):
    @yr.invoke
    def echo(value):
        return value

    values = [
        True,
        3.14,
        "unicode-\u262f",
        b"\x00\x01bytes",
        (1, "two", False),
        {"nested": [1, {"x": "y"}]},
        {"a", "b", "c"},
    ]
    for value in values:
        assert yr.get(yr.put(value)) == value
        assert yr.get(echo.invoke(value), timeout=120) == value


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


@pytest.mark.smoke
def test_invoke_options_env_vars(init_yr, require_remote_python_runtime):
    key = "YR_OFF_CLUSTER_SMOKE_ENV"
    value = _unique_name("env")
    opt = yr.InvokeOptions()
    opt.env_vars = {key: value}

    @yr.invoke
    def read_env(name):
        import os
        return os.getenv(name)

    assert yr.get(read_env.options(opt).invoke(key), timeout=120) == value


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


@pytest.mark.smoke
def test_kv_write_with_params(init_yr):
    key = _unique_name("off-cluster-kv-param")
    ttl_key = _unique_name("off-cluster-kv-ttl")
    try:
        set_param = yr.SetParam()
        set_param.existence = yr.ExistenceOpt.NX
        set_param.write_mode = yr.WriteMode.NONE_L2_CACHE_EVICT
        set_param.ttl_second = 0
        yr.kv_write_with_param(key, b"abcdef", set_param)
        try:
            yr.kv_write_with_param(key, b"changed", set_param)
        except RuntimeError:
            pass
        assert yr.kv_read(key) == b"abcdef"

        ttl_param = yr.SetParam()
        ttl_param.existence = yr.ExistenceOpt.NONE
        ttl_param.write_mode = yr.WriteMode.NONE_L2_CACHE_EVICT
        ttl_param.ttl_second = 1
        yr.kv_write_with_param(ttl_key, b"short-lived", ttl_param)
        assert yr.kv_read(ttl_key) == b"short-lived"
        time.sleep(1.5)
        with pytest.raises(RuntimeError):
            yr.kv_read(ttl_key, 1)
    finally:
        for cleanup_key in (key, ttl_key):
            try:
                yr.kv_del(cleanup_key)
            except RuntimeError:
                pass


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
    ready, not_ready = yr.wait([ref], wait_num=1, timeout=240)
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
        assert yr.get(echo.invoke(i), timeout=120) == i


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
    sandbox_id = _extract_sandbox_id(create.stdout)
    try:
        listed = _run_yrcli("sandbox", "list", "--namespace", namespace)
        assert sandbox_id in listed.stdout
        queried = _run_yrcli("sandbox", "query", sandbox_id)
        assert sandbox_id in queried.stdout
    finally:
        _run_yrcli("sandbox", "delete", sandbox_id)


@pytest.mark.smoke
def test_yrcli_sandbox_port_forwarding(require_plain_http_for_yrcli):
    namespace = "offcluster"
    name = _unique_name("yrcli-port")
    port = int(os.getenv("YRCLI_VERIFY_PORT", "8080"))
    create = _run_yrcli(
        "sandbox",
        "create",
        "--namespace",
        namespace,
        "--name",
        name,
        "--port",
        str(port),
        timeout=YRCLI_SANDBOX_CREATE_TIMEOUT,
    )
    sandbox_id = _extract_sandbox_id(create.stdout)
    gateway_url = _extract_port_url(create.stdout, port)
    try:
        started = _run_yrcli(
            "exec",
            sandbox_id,
            _remote_python_http_server_command(port),
            timeout=YRCLI_SANDBOX_EXEC_TIMEOUT,
        )
        assert "ready" in started.stdout
        _wait_any_url_contains(_gateway_url_candidates(gateway_url), "yrcli-port-forward-ok", timeout=60)
    finally:
        _run_yrcli("sandbox", "delete", sandbox_id)


@pytest.mark.smoke
def test_yrcli_sandbox_reverse_tunnel(require_plain_http_for_yrcli):
    upstream = _start_local_upstream()
    host, port = upstream.server_address
    name = _unique_name("yrcli-tunnel")
    instance_id = None
    proc = None
    try:
        proc = _start_tunnel_create(name, f"{host}:{port}")
        instance_id, output = _wait_for_tunnel_create(proc)
        assert "sandbox upstream proxy: http://127.0.0.1:8766" in output
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
            _run_yrcli("sandbox", "delete", instance_id)


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


@pytest.mark.smoke
def test_faas_sse_stream(require_plain_http_for_yrcli, tmp_path):
    namespace = "faaspy"
    function = _unique_name("yrcli-sse").replace("-", "")
    full_name = f"0@{namespace}@{function}"
    runtime = _get_faas_runtime()
    _ensure_faas_runtime(runtime)
    code_dir = tmp_path / "faas-sse"
    code_dir.mkdir()
    handler_path = code_dir / "handler.py"
    handler_path.write_text(
        "import json\n"
        "import time\n"
        "\n"
        "def handler(event, context):\n"
        "    for i in range(1, 11):\n"
        "        context.get_stream().write(json.dumps({\n"
        "            'id': i,\n"
        "            'content': 'message-%d' % i,\n"
        "            'echo': event.get('text') if isinstance(event, dict) else event,\n"
        "        }))\n"
        "        time.sleep(0.1)\n"
        "    return {'ok': True, 'echo': event}\n",
        encoding="utf-8",
    )
    function_json = tmp_path / "function-sse.json"
    function_json.write_text(
        json.dumps(
            {
                "name": full_name,
                "runtime": runtime,
                "description": "yrcli off-cluster SSE smoke handler",
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
        status, body = _invoke_faas_short_http(
            namespace,
            function,
            {"text": "sse-ping"},
            headers={
                "Accept": "text/event-stream",
            },
            timeout=150,
        )
        assert status == 200
        for i in range(1, 11):
            assert f'"id": {i}' in body, body
            assert f'"content": "message-{i}"' in body, body
        assert '"echo": "sse-ping"' in body, body
        assert "[DONE]" in body, body
    finally:
        _run_yrcli("delete", "-f", f"{namespace}@{function}", "--no-clear-package")


@pytest.mark.smoke
def test_faas_agent_session_wait_notify(require_plain_http_for_yrcli, tmp_path):
    """Verify AI Agent session wait/notify and affinity on the same instance."""
    namespace = "faaspy"
    function = _unique_name("yrcli-session").replace("-", "")
    full_name = f"0@{namespace}@{function}"
    session_id = _unique_name("agent-session")
    runtime = _get_faas_runtime()
    _ensure_faas_runtime(runtime)
    code_dir = tmp_path / "faas-session"
    code_dir.mkdir()
    handler_path = code_dir / "handler.py"
    handler_path.write_text(
        "import socket\n"
        "\n"
        "def handler(event, context):\n"
        "    hostname = socket.gethostname()\n"
        "    if isinstance(event, dict) and event.get('action') == 'ping':\n"
        "        return {'ok': True, 'phase': 'ping', 'hostname': hostname}\n"
        "\n"
        "    session_svc = context.get_session_service()\n"
        "    sess = session_svc.load_session()\n"
        "    if sess is None:\n"
        "        return {'ok': False, 'error': 'session unavailable', 'hostname': hostname}\n"
        "\n"
        "    if isinstance(event, dict) and event.get('action') == 'notify':\n"
        "        sess.notify(event.get('payload') or {})\n"
        "        return {'ok': True, 'phase': 'notify', 'hostname': hostname}\n"
        "\n"
        "    payload = sess.wait_for_notify(180000)\n"
        "    if payload is None:\n"
        "        return {'ok': False, 'error': 'timeout', 'hostname': hostname}\n"
        "\n"
        "    histories = sess.get_histories()\n"
        "    histories.append('notified:' + str(payload.get('message', '')))\n"
        "    sess.set_histories(histories)\n"
        "    return {\n"
        "        'ok': True,\n"
        "        'phase': 'main',\n"
        "        'payload': payload,\n"
        "        'histories': sess.get_histories(),\n"
        "        'hostname': hostname,\n"
        "    }\n",
        encoding="utf-8",
    )
    function_json = tmp_path / "function-session.json"
    function_json.write_text(
        json.dumps(
            {
                "name": full_name,
                "runtime": runtime,
                "description": "yrcli off-cluster agent session smoke handler",
                "handler": "handler.handler",
                "kind": "faas",
                "enableAgentSession": True,
                "cpu": 300,
                "memory": 128,
                "timeout": 300,
                "customResources": {},
                "environment": {},
                "extendedHandler": {},
                "extendedTimeout": {},
                "minInstance": "1",
                "maxInstance": "1",
                "concurrentNum": "2",
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

    warmup_deadline = time.time() + 120
    while time.time() < warmup_deadline:
        try:
            warmup_status, warmup_body = _invoke_faas_short_http(
                namespace,
                function,
                {"action": "ping"},
                timeout=30,
            )
            if warmup_status == 200:
                warmup_value = _decode_json_body(warmup_body)
                if warmup_value.get("phase") == "ping":
                    break
        except (AssertionError, TimeoutError, urllib.error.URLError):
            pass
        time.sleep(3)
    else:
        raise AssertionError("function warmup ping did not succeed before session test")

    main_thread = None
    try:
        main_result = {}
        main_error = {}

        def _run_main_invoke():
            try:
                status, body = _invoke_faas_short_http(
                    namespace,
                    function,
                    {"text": "start"},
                    headers=_build_session_header(session_id),
                    timeout=300,
                )
                main_result["status"] = status
                main_result["body"] = body
            except Exception as exc:
                main_error["error"] = exc

        main_thread = threading.Thread(target=_run_main_invoke)
        main_thread.start()

        notify_status = None
        notify_body = None
        notify_error = None
        deadline = time.time() + 240
        while main_thread.is_alive() and time.time() < deadline:
            try:
                notify_status, notify_body = _invoke_faas_short_http(
                    namespace,
                    function,
                    {"action": "notify", "payload": {"message": "hello-session"}},
                    headers=_build_session_header(session_id),
                    timeout=30,
                )
            except (AssertionError, TimeoutError, urllib.error.URLError) as exc:
                notify_error = exc
                if isinstance(exc, AssertionError) and "over-acquire limit exceeded" not in str(exc):
                    raise
            time.sleep(3)
        assert notify_status == 200, notify_body or notify_error

        main_thread.join(timeout=120)
        assert "error" not in main_error, main_error.get("error")
        notify_value = _decode_json_body(notify_body)
        assert notify_value.get("ok") is True, notify_value
        assert notify_value.get("phase") == "notify", notify_value
        notify_hostname = notify_value.get("hostname")
        assert notify_hostname, notify_value

        assert main_result.get("status") == 200, main_result.get("body")
        main_value = _decode_json_body(main_result["body"])
        assert main_value.get("ok") is True, main_value
        assert main_value.get("phase") == "main", main_value
        assert main_value.get("payload", {}).get("message") == "hello-session", main_value
        assert "notified:hello-session" in main_value.get("histories", []), main_value
        assert main_value.get("hostname") == notify_hostname, (
            f"session affinity mismatch: main={main_value.get('hostname')} "
            f"notify={notify_hostname}"
        )
    finally:
        if main_thread is not None:
            main_thread.join(timeout=300)
        _run_yrcli("delete", "-f", f"{namespace}@{function}", "--no-clear-package")
