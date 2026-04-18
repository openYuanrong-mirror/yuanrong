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

Off-cluster known limitations (marked as skip):
  - Worker cannot read-back ObjectRef data stored on the driver's local DS
  - Instance terminate() may timeout (driver cannot control remote lifecycle)

Run:
    export YR_SERVER_ADDRESS=<ip:port>
    export YR_JWT_TOKEN=<jwt_token>   # optional
    /path/to/python3.9 -m pytest -s -vv -p no:conftest test_off_cluster.py

    # or via the wrapper script:
    bash run_off_cluster_test.sh -a <ip:port>
"""

import os
import time
import pytest
import yr

pytestmark = pytest.mark.off_cluster


def _get_addr():
    addr = os.getenv("YR_SERVER_ADDRESS", "")
    if not addr:
        raise ValueError("YR_SERVER_ADDRESS not set")
    return addr


def _get_jwt_token():
    return os.getenv("YR_JWT_TOKEN", "")


def _build_conf():
    addr = _get_addr()
    return yr.Config(
        server_address=addr,
        ds_address=addr,
        in_cluster=False,
        enable_tls=True,
        log_level="DEBUG",
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


@pytest.mark.skip(reason="off-cluster: worker cannot read-back ObjectRef from driver's local DS")
@pytest.mark.smoke
def test_invoke_with_object_ref_arg(init_yr):
    """Pass ObjectRef as argument — runtime should auto-resolve on worker side."""
    @yr.invoke
    def get_nums():
        return [10, 20, 30]

    @yr.invoke
    def dis_sum(args):
        return sum(args)

    nums_ref = get_nums.invoke()
    ref = dis_sum.invoke(nums_ref)
    assert yr.get(ref, timeout=120) == 60


@pytest.mark.skip(reason="off-cluster: worker cannot read-back ObjectRef from driver's local DS")
@pytest.mark.smoke
def test_invoke_with_nested_ref(init_yr):
    """Nested ObjectRefs inside a list argument."""
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


@pytest.mark.skip(reason="off-cluster: large bytes result stored on worker DS, driver cannot read back")
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
    opt.name = "off-cluster-test-actor"
    opt.concurrency = 1
    ins = Counter.options(opt).invoke()
    assert yr.get(ins.add.invoke()) == 1

    # Same named instance should share state
    ins2 = Counter.options(opt).invoke()
    assert yr.get(ins2.add.invoke()) == 2


@pytest.mark.skip(reason="off-cluster: worker cannot read-back ObjectRef from driver's local DS")
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
    refs = [counter.add.invoke() for _ in range(10)]
    results = yr.get(refs)
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

    refs = [may_throw.invoke(i) for i in range(6)]
    ready, not_ready = yr.wait(refs, wait_num=6)
    assert len(not_ready) == 0
    assert len(ready) == 6
    for i, ref in enumerate(ready):
        if i % 2 != 0:
            assert yr.get(ref) == i
        else:
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
