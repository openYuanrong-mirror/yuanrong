#!/usr/bin/env python3
# coding=UTF-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
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

"""
node_role ST tests: verify object and KV interface stability when
datasystem workers are split into master-role (ring members) and
worker-role (SHM cache forwarders) nodes.

Environment variables (all required):
  YR_PYTHON_FUNC_ID        function ID for yr.init
  YR_MASTER_ADDRESS        meta-service address (host:port)
  YR_GLOG_LOG_DIR          log output directory (or GLOG_log_dir)

  YR_WORKER_DS_ADDRESS     address of a node_role=worker ds_worker
  YR_WORKER_PROXY_ADDRESS  gRPC proxy address on the worker-role node
  YR_MASTER_DS_ADDRESS     address of a node_role=master ds_worker
  YR_MASTER_PROXY_ADDRESS  gRPC proxy address on the master-role node

  YR_WORKER_DEPLOY_PATH    deploy_path for the worker-role node (used to
                           locate the ready-file and spawn restart)

Defaults match the manual 2-node cluster on 172.21.0.5:
  worker ds  :24869  worker proxy gRPC :37711
  master ds  :24883  master proxy gRPC :21766
  meta       :19644
"""

import os
import signal
import subprocess
import time
import uuid

import pytest
import yr

# ---------------------------------------------------------------------------
# Addresses (fall back to the hand-started cluster defaults)
# ---------------------------------------------------------------------------
_IP = "172.21.0.5"

WORKER_DS_ADDR   = os.getenv("YR_WORKER_DS_ADDRESS",   f"{_IP}:24869")
WORKER_PROXY_ADDR = os.getenv("YR_WORKER_PROXY_ADDRESS", f"{_IP}:37711")
MASTER_DS_ADDR   = os.getenv("YR_MASTER_DS_ADDRESS",   f"{_IP}:24883")
MASTER_PROXY_ADDR = os.getenv("YR_MASTER_PROXY_ADDRESS", f"{_IP}:21766")

LOG_DIR = os.getenv("GLOG_log_dir", os.getenv("YR_GLOG_LOG_DIR", "/tmp/yr_node_role_test"))

WORKER_DEPLOY_PATH = os.getenv("YR_WORKER_DEPLOY_PATH", "/tmp/bbb")

os.makedirs(LOG_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _make_yr_config(ds_addr: str, proxy_addr: str) -> yr.Config:
    return yr.Config(
        server_address=proxy_addr,
        ds_address=ds_addr,
        in_cluster=True,
        log_level="INFO",
        log_dir=LOG_DIR,
    )


@pytest.fixture
def yr_via_worker():
    """yr client routed through the node_role=worker ds."""
    yr.init(_make_yr_config(WORKER_DS_ADDR, WORKER_PROXY_ADDR))
    yield
    yr.finalize()


@pytest.fixture
def yr_via_master():
    """yr client routed directly through the node_role=master ds."""
    yr.init(_make_yr_config(MASTER_DS_ADDR, MASTER_PROXY_ADDR))
    yield
    yr.finalize()


# ---------------------------------------------------------------------------
# Object interface tests
# ---------------------------------------------------------------------------
class TestObjectViaWorkerRole:
    """yr.put / yr.get through a node_role=worker ds_worker."""

    @pytest.mark.node_role
    @pytest.mark.smoke
    def test_put_get_scalar(self, yr_via_worker):
        ref = yr.put(42)
        assert yr.get(ref, 30) == 42

    @pytest.mark.node_role
    @pytest.mark.smoke
    def test_put_get_bytes(self, yr_via_worker):
        payload = b"node_role_worker_" + uuid.uuid4().bytes
        ref = yr.put(payload)
        assert yr.get(ref, 30) == payload

    @pytest.mark.node_role
    def test_put_get_large_object(self, yr_via_worker):
        """1 MB object – exercises forwarding path for large payloads."""
        payload = b"x" * (1 * 1024 * 1024)
        ref = yr.put(payload)
        assert yr.get(ref, 60) == payload

    @pytest.mark.node_role
    def test_concurrent_puts(self, yr_via_worker):
        """Multiple concurrent puts/gets via the forwarding path."""
        n = 20
        refs = [yr.put(i) for i in range(n)]
        results = yr.get(refs, 60)
        assert results == list(range(n))


class TestObjectViaMasterRole:
    """yr.put / yr.get directly through the node_role=master ds_worker (baseline)."""

    @pytest.mark.node_role
    @pytest.mark.smoke
    def test_put_get_scalar(self, yr_via_master):
        ref = yr.put(42)
        assert yr.get(ref, 30) == 42

    @pytest.mark.node_role
    @pytest.mark.smoke
    def test_put_get_bytes(self, yr_via_master):
        payload = b"node_role_master_" + uuid.uuid4().bytes
        ref = yr.put(payload)
        assert yr.get(ref, 30) == payload

    @pytest.mark.node_role
    def test_put_get_large_object(self, yr_via_master):
        payload = b"y" * (1 * 1024 * 1024)
        ref = yr.put(payload)
        assert yr.get(ref, 60) == payload


# ---------------------------------------------------------------------------
# KV interface tests
# ---------------------------------------------------------------------------
class TestKVViaWorkerRole:
    """yr.kv_write / yr.kv_read through a node_role=worker ds_worker."""

    @pytest.mark.node_role
    @pytest.mark.smoke
    def test_kv_write_read(self, yr_via_worker):
        key = f"nr_worker_{uuid.uuid4().hex[:8]}"
        val = b"hello_from_worker_role"
        yr.kv_write(key, val)
        assert yr.kv_read(key) == val
        yr.kv_del(key)

    @pytest.mark.node_role
    def test_kv_overwrite(self, yr_via_worker):
        key = f"nr_worker_ow_{uuid.uuid4().hex[:8]}"
        yr.kv_write(key, b"v1")
        yr.kv_write(key, b"v2")
        assert yr.kv_read(key) == b"v2"
        yr.kv_del(key)

    @pytest.mark.node_role
    def test_kv_nx_flag(self, yr_via_worker):
        key = f"nr_worker_nx_{uuid.uuid4().hex[:8]}"
        yr.kv_write(key, b"first", yr.ExistenceOpt.NONE)
        with pytest.raises(Exception):
            yr.kv_write(key, b"second", yr.ExistenceOpt.NX)
        assert yr.kv_read(key) == b"first"
        yr.kv_del(key)

    @pytest.mark.node_role
    def test_kv_large_value(self, yr_via_worker):
        key = f"nr_worker_large_{uuid.uuid4().hex[:8]}"
        val = b"z" * (512 * 1024)
        yr.kv_write(key, val)
        assert yr.kv_read(key) == val
        yr.kv_del(key)

    @pytest.mark.node_role
    def test_kv_batch_keys(self, yr_via_worker):
        """Write several keys and verify all are readable."""
        n = 50
        keys = [f"nr_batch_{uuid.uuid4().hex[:6]}_{i}" for i in range(n)]
        for i, k in enumerate(keys):
            yr.kv_write(k, str(i).encode())
        for i, k in enumerate(keys):
            assert yr.kv_read(k) == str(i).encode()
        for k in keys:
            yr.kv_del(k)


class TestKVViaMasterRole:
    """yr.kv_write / yr.kv_read directly on the node_role=master ds_worker."""

    @pytest.mark.node_role
    @pytest.mark.smoke
    def test_kv_write_read(self, yr_via_master):
        key = f"nr_master_{uuid.uuid4().hex[:8]}"
        val = b"hello_from_master_role"
        yr.kv_write(key, val)
        assert yr.kv_read(key) == val
        yr.kv_del(key)

    @pytest.mark.node_role
    def test_kv_batch_keys(self, yr_via_master):
        n = 50
        keys = [f"nr_mbatch_{uuid.uuid4().hex[:6]}_{i}" for i in range(n)]
        for i, k in enumerate(keys):
            yr.kv_write(k, str(i).encode())
        for i, k in enumerate(keys):
            assert yr.kv_read(k) == str(i).encode()
        for k in keys:
            yr.kv_del(k)


# ---------------------------------------------------------------------------
# Stability: worker-role ds restart
# ---------------------------------------------------------------------------
def _find_worker_role_pid() -> int:
    """Return PID of the node_role=worker datasystem_worker process."""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "datasystem_worker.*node_role=worker"],
            text=True
        ).strip()
        pids = [int(p) for p in out.splitlines() if p.strip()]
        if not pids:
            raise RuntimeError("no node_role=worker datasystem_worker found")
        return pids[0]
    except subprocess.CalledProcessError:
        raise RuntimeError("no node_role=worker datasystem_worker found")


def _get_cmdline(pid: int):
    """Return argv list for given pid."""
    with open(f"/proc/{pid}/cmdline", "rb") as f:
        return f.read().split(b"\x00")[:-1]


def _wait_for_ready(ready_path: str, timeout: int = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(ready_path):
            return True
        time.sleep(0.5)
    return False


def _extract_flag(argv, flag: str, default=""):
    """Extract value of -flag=value or -flag value from argv list."""
    for i, a in enumerate(argv):
        if isinstance(a, bytes):
            a = a.decode()
        if a.startswith(f"-{flag}="):
            return a.split("=", 1)[1]
        if a == f"-{flag}" and i + 1 < len(argv):
            nxt = argv[i + 1]
            return nxt.decode() if isinstance(nxt, bytes) else nxt
    return default


class TestWorkerRoleRestartStability:
    """Verify data integrity and reconnect behaviour when the
    node_role=worker ds_worker is killed and restarted."""

    @pytest.mark.node_role
    @pytest.mark.slow
    def test_kv_persists_through_worker_restart(self):
        """
        1. Write KV data via master-role ds (data lives on the ring).
        2. Kill the worker-role ds.
        3. Verify data is still readable via master-role ds.
        4. Restart the worker-role ds.
        5. Verify data is still readable via worker-role ds.
        """
        key = f"nr_restart_kv_{uuid.uuid4().hex[:8]}"
        val = b"survives_worker_restart"

        # ---- step 1: write via master-role ds ----
        yr.init(_make_yr_config(MASTER_DS_ADDR, MASTER_PROXY_ADDR))
        try:
            yr.kv_write(key, val)
            assert yr.kv_read(key) == val
        finally:
            yr.finalize()

        # ---- step 2: kill the worker-role ds ----
        pid = _find_worker_role_pid()
        argv = _get_cmdline(pid)
        ready_path = _extract_flag(argv, "ready_check_path")
        assert ready_path, "could not find -ready_check_path in worker cmdline"

        os.kill(pid, signal.SIGTERM)
        # wait for process to exit
        for _ in range(30):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except ProcessLookupError:
                break

        # ---- step 3: data still accessible via master-role ds ----
        yr.init(_make_yr_config(MASTER_DS_ADDR, MASTER_PROXY_ADDR))
        try:
            assert yr.kv_read(key) == val, \
                "KV data lost after worker-role ds was killed"
        finally:
            yr.finalize()

        # ---- step 4: restart the worker-role ds ----
        if os.path.exists(ready_path):
            os.remove(ready_path)
        cmd = [a.decode() if isinstance(a, bytes) else a for a in argv]
        proc = subprocess.Popen(cmd,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        assert _wait_for_ready(ready_path, timeout=60), \
            f"worker-role ds did not become ready within 60 s (ready_path={ready_path})"

        # ---- step 5: data accessible via worker-role ds, then cleanup ----
        yr.init(_make_yr_config(WORKER_DS_ADDR, WORKER_PROXY_ADDR))
        try:
            assert yr.kv_read(key) == val, \
                "KV data not accessible via worker-role ds after restart"
            yr.kv_del(key)
        finally:
            yr.finalize()

        proc.terminate()
        proc.wait(timeout=10)

    @pytest.mark.node_role
    @pytest.mark.slow
    def test_object_stable_through_worker_restart(self):
        """
        Verify that objects stored on the master-role ds remain accessible
        during and after the worker-role ds is killed and restarted.
        Objects are session-scoped, so this test uses a single yr session
        (connected to master-role ds) throughout the restart lifecycle.
        """
        payload = b"object_survives_" + uuid.uuid4().bytes

        yr.init(_make_yr_config(MASTER_DS_ADDR, MASTER_PROXY_ADDR))
        try:
            ref = yr.put(payload)
            assert yr.get(ref, 30) == payload, "initial read failed"

            # ---- kill the worker-role ds ----
            pid = _find_worker_role_pid()
            argv = _get_cmdline(pid)
            ready_path = _extract_flag(argv, "ready_check_path")
            assert ready_path

            os.kill(pid, signal.SIGTERM)
            for _ in range(30):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.5)
                except ProcessLookupError:
                    break

            # ---- object still accessible via master-role ds while worker is down ----
            assert yr.get(ref, 30) == payload, \
                "object lost after worker-role ds was killed"

            # ---- restart the worker-role ds ----
            if os.path.exists(ready_path):
                os.remove(ready_path)
            cmd = [a.decode() if isinstance(a, bytes) else a for a in argv]
            proc = subprocess.Popen(cmd,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            assert _wait_for_ready(ready_path, timeout=60), \
                "worker-role ds did not become ready after restart"

            # ---- object still accessible after worker restart ----
            assert yr.get(ref, 30) == payload, \
                "object not accessible after worker-role ds restarted"

            proc.terminate()
            proc.wait(timeout=10)
        finally:
            yr.finalize()


# ---------------------------------------------------------------------------
# Large-scale stress test
# ---------------------------------------------------------------------------
class TestNodeRoleLargeScale:
    """
    High-volume concurrent put/get and KV operations across both roles.
    Intended for k8s cluster validation (--scale flag or directly).
    """

    @pytest.mark.node_role
    @pytest.mark.slow
    def test_large_scale_kv_via_worker_role(self, yr_via_worker):
        """Write and read 1000 KV entries through the worker-role ds."""
        n = 1000
        keys = [f"ls_kv_{uuid.uuid4().hex[:6]}_{i}" for i in range(n)]
        expected = {k: f"val_{i}".encode() for i, k in enumerate(keys)}

        for k, v in expected.items():
            yr.kv_write(k, v)

        for k, v in expected.items():
            assert yr.kv_read(k) == v, f"mismatch at key {k}"

        for k in keys:
            yr.kv_del(k)

    @pytest.mark.node_role
    @pytest.mark.slow
    def test_large_scale_object_via_worker_role(self, yr_via_worker):
        """Put and get 200 objects of 64 KB each via worker-role ds."""
        n = 200
        chunk = 64 * 1024
        payloads = [bytes([i % 256]) * chunk for i in range(n)]
        refs = [yr.put(p) for p in payloads]
        results = yr.get(refs, 120)
        assert results == payloads

    @pytest.mark.node_role
    @pytest.mark.slow
    def test_large_scale_mixed_kv_and_object(self, yr_via_worker):
        """
        Interleave KV writes and object puts to exercise concurrent
        forwarding through the worker-role ds.
        """
        n = 300
        kv_keys = [f"ls_mix_kv_{uuid.uuid4().hex[:6]}_{i}" for i in range(n)]
        obj_refs = []

        # interleave writes
        for i in range(n):
            yr.kv_write(kv_keys[i], str(i).encode())
            obj_refs.append(yr.put(i))

        # verify KV
        for i, k in enumerate(kv_keys):
            assert yr.kv_read(k) == str(i).encode(), f"KV mismatch at {k}"

        # verify objects
        for i, ref in enumerate(obj_refs):
            assert yr.get(ref, 60) == i, f"object mismatch at index {i}"

        for k in kv_keys:
            yr.kv_del(k)

    @pytest.mark.node_role
    @pytest.mark.slow
    def test_worker_role_scale_up_down_kv(self):
        """
        Simulates scale-down (kill worker-role ds) then scale-up (restart)
        under continuous KV load on the master-role ds.

        Pattern:
          - pre-populate 500 keys via master-role ds
          - kill worker-role ds
          - verify all 500 keys via master-role ds
          - restart worker-role ds
          - verify all 500 keys via worker-role ds
          - write 500 more keys via worker-role ds
          - verify all 1000 keys via master-role ds
        """
        n = 500
        keys = [f"scale_kv_{uuid.uuid4().hex[:6]}_{i}" for i in range(n)]

        # --- pre-populate via master-role ds ---
        yr.init(_make_yr_config(MASTER_DS_ADDR, MASTER_PROXY_ADDR))
        try:
            for i, k in enumerate(keys):
                yr.kv_write(k, str(i).encode())
        finally:
            yr.finalize()

        # --- kill worker-role ds ---
        pid = _find_worker_role_pid()
        argv = _get_cmdline(pid)
        ready_path = _extract_flag(argv, "ready_check_path")
        assert ready_path

        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except ProcessLookupError:
                break

        # --- all keys still on master-role ds ---
        yr.init(_make_yr_config(MASTER_DS_ADDR, MASTER_PROXY_ADDR))
        try:
            for i, k in enumerate(keys):
                assert yr.kv_read(k) == str(i).encode(), \
                    f"master: key {k} lost after worker kill"
        finally:
            yr.finalize()

        # --- restart worker-role ds ---
        if os.path.exists(ready_path):
            os.remove(ready_path)
        cmd = [a.decode() if isinstance(a, bytes) else a for a in argv]
        proc = subprocess.Popen(cmd,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        assert _wait_for_ready(ready_path, timeout=60), \
            "worker-role ds did not come back after restart"

        # --- verify existing keys via worker-role ds ---
        yr.init(_make_yr_config(WORKER_DS_ADDR, WORKER_PROXY_ADDR))
        try:
            for i, k in enumerate(keys):
                assert yr.kv_read(k) == str(i).encode(), \
                    f"worker: key {k} missing after restart"

            # --- write 500 more keys via worker-role ds ---
            extra_keys = [f"scale_extra_{uuid.uuid4().hex[:6]}_{i}"
                          for i in range(n)]
            for i, k in enumerate(extra_keys):
                yr.kv_write(k, f"extra_{i}".encode())
        finally:
            yr.finalize()

        # --- verify all 1000 keys on master-role ds ---
        yr.init(_make_yr_config(MASTER_DS_ADDR, MASTER_PROXY_ADDR))
        try:
            for i, k in enumerate(keys):
                assert yr.kv_read(k) == str(i).encode()
            for i, k in enumerate(extra_keys):
                assert yr.kv_read(k) == f"extra_{i}".encode()
        finally:
            yr.finalize()

        # cleanup
        yr.init(_make_yr_config(MASTER_DS_ADDR, MASTER_PROXY_ADDR))
        try:
            for k in keys + extra_keys:
                yr.kv_del(k)
        finally:
            yr.finalize()

        proc.terminate()
        proc.wait(timeout=10)
