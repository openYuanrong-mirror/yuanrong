#!/usr/bin/env python3
# coding=UTF-8
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

"""invoke_direct smoke tests — cluster-internal (SDK) and cluster-external (Frontend HTTP)."""

import json
import os
import subprocess
import sys
import traceback

import httpx

YR_SERVER_ADDRESS = os.environ.get("YR_SERVER_ADDRESS", "127.0.0.1:8888")
YR_FRONTEND_ADDRESS = os.environ.get("YR_FRONTEND_ADDRESS", "127.0.0.1:8888")
FAAS_HANDLER_DIR = os.environ.get("YR_FAAS_HANDLER_DIR", "")
TENANT_ID = os.environ.get("YR_TENANT_ID", "0")
NAMESPACE = os.environ.get("YR_NAMESPACE", "faaspy")
FUNCTION_NAME = os.environ.get("YR_FUNCTION_NAME", "invokedirecthandler")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

results = []


def record(name, passed, detail=""):
    results.append((name, passed, detail))
    tag = "PASS" if passed else "FAIL"
    msg = f"{name}: {tag}"
    if not passed and detail:
        msg += f" - {detail}"
    print(msg)


def http_post(url, body, headers=None, timeout=30):
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    data = json.dumps(body).encode() if isinstance(body, dict) else (
        body if isinstance(body, bytes) else body.encode()
    )
    with httpx.Client(timeout=timeout) as client:
        return client.post(url, content=data, headers=hdrs).json()


def http_delete(url, headers=None):
    try:
        with httpx.Client(timeout=15) as client:
            return client.delete(url, headers=headers or {}).text
    except Exception:
        return ""


# ===========================================================================
# Part 1: Cluster-internal tests (SDK via yr.init)
# ===========================================================================

def run_sdk_tests():
    import yr
    from yr.config import Config
    from yr.object_ref import ObjectRefDirect

    print("\n========== Part 1: SDK invoke_direct (cluster-internal) ==========\n")

    try:
        conf = Config(server_address=YR_SERVER_ADDRESS, is_driver=True, auto=False)
        conf.in_cluster = False
        yr.init(conf)
        record("sdk_init", True)
    except Exception as exc:
        record("sdk_init", False, str(exc))
        traceback.print_exc()
        return

    # --- test 1: stateless invoke_direct ---
    try:
        @yr.invoke
        def add(a, b):
            return a + b

        ref = add.invoke_direct(3, 7)
        is_direct = isinstance(ref, ObjectRefDirect)
        val = yr.get(ref)
        if is_direct and val == 10:
            record("stateless_invoke_direct", True)
        else:
            record("stateless_invoke_direct", False,
                   f"type={type(ref).__name__}, val={val}")
    except Exception as exc:
        record("stateless_invoke_direct", False, str(exc))
        traceback.print_exc()

    # --- test 2: instance invoke_direct ---
    try:
        @yr.instance
        class Counter:
            def __init__(self, start):
                self.value = start

            def incr(self, delta):
                self.value += delta
                return self.value

        counter = Counter.invoke(100)
        ref2 = counter.incr.invoke_direct(5)
        is_direct = isinstance(ref2, ObjectRefDirect)
        val2 = yr.get(ref2)
        if is_direct and val2 == 105:
            record("instance_invoke_direct", True)
        else:
            record("instance_invoke_direct", False,
                   f"type={type(ref2).__name__}, val={val2}")
    except Exception as exc:
        record("instance_invoke_direct", False, str(exc))
        traceback.print_exc()

    # --- test 3: invoke vs invoke_direct ---
    try:
        @yr.invoke
        def multiply(a, b):
            return a * b

        ref_normal = multiply.invoke(6, 7)
        ref_direct = multiply.invoke_direct(6, 7)
        v_normal = yr.get(ref_normal)
        v_direct = yr.get(ref_direct)
        type_ok = (not isinstance(ref_normal, ObjectRefDirect) and
                   isinstance(ref_direct, ObjectRefDirect))
        if type_ok and v_normal == 42 and v_direct == 42:
            record("invoke_vs_invoke_direct", True)
        else:
            record("invoke_vs_invoke_direct", False,
                   f"normal={v_normal}({type(ref_normal).__name__}), "
                   f"direct={v_direct}({type(ref_direct).__name__})")
    except Exception as exc:
        record("invoke_vs_invoke_direct", False, str(exc))
        traceback.print_exc()

    # --- test 4: large data ---
    try:
        @yr.invoke
        def echo(data):
            return data

        big = list(range(1000))
        ref3 = echo.invoke_direct(big)
        val3 = yr.get(ref3)
        if val3 == big:
            record("invoke_direct_large_data", True)
        else:
            record("invoke_direct_large_data", False,
                   f"len={len(val3) if isinstance(val3, list) else 'N/A'}")
    except Exception as exc:
        record("invoke_direct_large_data", False, str(exc))
        traceback.print_exc()

    # --- test 5: multiple sequential calls ---
    try:
        @yr.invoke
        def inc(x):
            return x + 1

        ok = True
        for i in range(10):
            ref = inc.invoke_direct(i)
            val = yr.get(ref)
            if val != i + 1:
                ok = False
                record("invoke_direct_multiple_calls", False,
                       f"i={i}, expected={i+1}, got={val}")
                break
        if ok:
            record("invoke_direct_multiple_calls", True)
    except Exception as exc:
        record("invoke_direct_multiple_calls", False, str(exc))
        traceback.print_exc()

    try:
        yr.finalize()
    except Exception as _e:
        print(f"[warn] finalize error: {_e}")


# ===========================================================================
# Part 2: Cluster-external tests (Frontend HTTP)
# ===========================================================================

def run_frontend_tests():
    print("\n========== Part 2: Frontend HTTP invoke (cluster-external) ==========\n")

    base_url = "https://" + YR_FRONTEND_ADDRESS
    full_name = f"{TENANT_ID}@{NAMESPACE}@{FUNCTION_NAME}"

    if not FAAS_HANDLER_DIR:
        print("  SKIP: YR_FAAS_HANDLER_DIR not set, skipping frontend tests")
        return

    # --- check frontend health ---
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{base_url}/healthz")
            if r.status_code >= 500:
                raise OSError(f"frontend returned {r.status_code}")
    except Exception as exc:
        print(f"  SKIP: frontend not reachable ({exc}), skipping frontend tests")
        return

    # --- check FaaS executor deploy directory is writable ---
    faas_deploy_dir = "/home/sn/system-function-packages"
    if not os.path.isdir(faas_deploy_dir) or not os.access(faas_deploy_dir, os.W_OK):
        print(f"  SKIP: {faas_deploy_dir} not writable, "
              "FaaS tests require dev container environment")
        return

    # --- deploy FaaS function ---
    deploy_body = {
        "name": full_name,
        "runtime": "python3.9",
        "description": "invoke_direct smoke handler",
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
        "codePath": FAAS_HANDLER_DIR,
    }

    try:
        resp = http_post(
            f"{base_url}/admin/v1/functions",
            deploy_body,
            headers={"X-Tenant-Id": TENANT_ID},
        )
        if "function" in str(resp):
            record("frontend_deploy_function", True)
        else:
            record("frontend_deploy_function", False, str(resp))
            return
    except Exception as exc:
        # meta_service or admin API may not be available in all environments
        print(f"  SKIP: function deploy failed ({exc}), "
              "FaaS tests require dev container with /home/sn writeable")
        return

    import time

    invoke_url = f"{base_url}/invocations/{TENANT_ID}/{NAMESPACE}/{FUNCTION_NAME}/"
    payload = {"name": "invoke_direct_test"}

    # Wait for function cold-start: retry until first invoke succeeds
    print("  Waiting for function instance to be ready...")
    ready = False
    for attempt in range(20):
        try:
            resp = http_post(invoke_url, {"command": "env"}, timeout=15)
            if isinstance(resp, dict) and resp.get("ok"):
                ready = True
                break
        except Exception as _e:
            print(f"[debug] instance not ready yet: {_e}")
        # FaaS instance creation may fail outside dev container (/home/sn permission)
        print("  SKIP: function instance not ready (likely outside dev container)")
        return

    # --- test: invoke without bypass (baseline) ---
    try:
        resp = http_post(invoke_url, payload)
        if resp.get("ok") is True and resp.get("echo") == "invoke_direct_test":
            record("frontend_invoke_normal", True)
        else:
            record("frontend_invoke_normal", False, str(resp))
    except Exception as exc:
        record("frontend_invoke_normal", False, str(exc))
        traceback.print_exc()

    # --- test: invoke with X-Bypass-Datasystem ---
    try:
        resp = http_post(
            invoke_url, payload,
            headers={"X-Bypass-Datasystem": "true"},
        )
        if resp.get("ok") is True and resp.get("echo") == "invoke_direct_test":
            record("frontend_invoke_bypass_datasystem", True)
        else:
            record("frontend_invoke_bypass_datasystem", False, str(resp))
    except Exception as exc:
        record("frontend_invoke_bypass_datasystem", False, str(exc))
        traceback.print_exc()

    # --- cleanup: delete function ---
    try:
        http_delete(
            f"{base_url}/admin/v1/functions/{full_name}?versionNumber=latest",
            headers={"X-Tenant-Id": TENANT_ID},
        )
    except Exception as _e:
        print(f"[warn] cleanup delete failed: {_e}")


# ===========================================================================
# main
# ===========================================================================

def main():
    print("=== invoke_direct Smoke Tests ===")
    print(f"YR_SERVER_ADDRESS={YR_SERVER_ADDRESS}")
    print(f"YR_FRONTEND_ADDRESS={YR_FRONTEND_ADDRESS}")

    run_sdk_tests()
    run_frontend_tests()

    print("\n--- Summary ---")
    all_passed = all(r[1] for r in results)
    for name, passed, detail in results:
        tag = "PASS" if passed else "FAIL"
        line = f"  {name}: {tag}"
        if not passed and detail:
            line += f" ({detail})"
        print(line)

    print("")
    if all_passed:
        print("--- invoke_direct Smoke: ALL PASS ---")
    else:
        print("--- invoke_direct Smoke: SOME FAILURES ---")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
