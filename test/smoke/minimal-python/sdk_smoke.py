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

import os
import sys
import traceback

import yr
from yr.config import Config

YR_RUNTIME = os.environ.get("YR_SMOKE_SERVER_ADDRESS", "127.0.0.1:8888")


def run_sdk_smoke():
    results = []

    print("--- SDK Smoke Results ---")

    try:
        conf = Config(server_address=YR_RUNTIME, is_driver=True, auto=False)
        conf.in_cluster = False
        yr.init(conf)
        results.append(("runtime init", True, ""))
        print("runtime init: PASS")
    except Exception as exc:
        results.append(("runtime init", False, str(exc)))
        print(f"runtime init: FAIL - {exc}")
        traceback.print_exc()

    try:
        @yr.invoke
        def add_one(x):
            return x + 1

        result = yr.get(add_one.invoke(1))
        if result == 2:
            results.append(("stateless(1) = 2", True, ""))
            print("stateless(1) = 2: PASS")
        else:
            detail = f"Expected 2, got {result}"
            results.append(("stateless(1) = 2", False, detail))
            print(f"stateless(1) = 2: FAIL - {detail}")
    except Exception as exc:
        results.append(("stateless(1) = 2", False, str(exc)))
        print(f"stateless(1) = 2: FAIL - {exc}")
        traceback.print_exc()

    try:
        @yr.instance
        class Counter:
            def __init__(self, start):
                self.value = start

            def add(self, n):
                self.value += n
                return self.value

            def get(self):
                return self.value

        counter = Counter.invoke(10)
        add_result = yr.get(counter.add.invoke(5))
        get_result = yr.get(counter.get.invoke())
        if add_result == 15 and get_result == 15:
            results.append(("Counter(10).add(5).get() = 15", True, ""))
            print("Counter(10).add(5).get() = 15: PASS")
        else:
            detail = f"Expected 15/15, got add={add_result}, get={get_result}"
            results.append(("Counter(10).add(5).get() = 15", False, detail))
            print(f"Counter(10).add(5).get() = 15: FAIL - {detail}")
    except Exception as exc:
        results.append(("Counter(10).add(5).get() = 15", False, str(exc)))
        print(f"Counter(10).add(5).get() = 15: FAIL - {exc}")
        traceback.print_exc()

    try:
        original = {"k": "v"}
        ref = yr.put(original)
        retrieved = yr.get(ref)
        if retrieved == original:
            results.append(("object round-trip", True, ""))
            print("object round-trip: PASS")
        else:
            detail = f"Expected {original}, got {retrieved}"
            results.append(("object round-trip", False, detail))
            print(f"object round-trip: FAIL - {detail}")
    except Exception as exc:
        results.append(("object round-trip", False, str(exc)))
        print(f"object round-trip: FAIL - {exc}")
        traceback.print_exc()

    try:
        @yr.invoke
        def expect_string(x):
            if not isinstance(x, str):
                raise TypeError("x must be string")
            return x

        try:
            yr.get(expect_string.invoke(123))
            results.append(("negative case raises exception", False, "No exception raised"))
            print("negative case raises exception: FAIL - No exception raised")
        except Exception:
            results.append(("negative case raises exception", True, ""))
            print("negative case raises exception: PASS")
    except Exception as exc:
        results.append(("negative case raises exception", False, str(exc)))
        print(f"negative case raises exception: FAIL - {exc}")
        traceback.print_exc()

    all_passed = all(result[1] for result in results)
    print("")
    if all_passed:
        print("--- SDK Smoke: ALL PASS ---")
    else:
        print("--- SDK Smoke: SOME FAILURES ---")
        for name, passed, error in results:
            if not passed:
                print(f"  {name}: {error}")

    try:
        yr.finalize()
    except Exception:
        pass

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    run_sdk_smoke()
