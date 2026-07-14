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
import sys
import threading
import types
import unittest
from unittest import mock

import yr


def lazy_exports():
    return yr.__dict__["_LAZY_EXPORTS"]


class TestLazyExports(unittest.TestCase):
    def tearDown(self):
        for name in ("RaceGauge", "RaceAlarm"):
            lazy_exports().pop(name, None)
            yr.__dict__.pop(name, None)
        for module_name in ("yr.tests.fake_metrics", "yr.tests.fake_alarm"):
            sys.modules.pop(module_name, None)

    def test_lazy_export_uses_importlib_when_module_is_partially_initialized(self):
        module_name = "yr.tests.fake_metrics"
        partial_module = types.ModuleType(module_name)
        sys.modules[module_name] = partial_module
        lazy_exports()["RaceGauge"] = (module_name, "Gauge")

        class Gauge:
            pass

        def finish_import(name):
            self.assertEqual(name, module_name)
            partial_module.Gauge = Gauge
            return partial_module

        with mock.patch.object(yr.importlib, "import_module", side_effect=finish_import) as import_module:
            self.assertIs(yr.RaceGauge, Gauge)

        import_module.assert_called_once_with(module_name)

    def test_lazy_export_is_cached_for_concurrent_access(self):
        module_name = "yr.tests.fake_metrics"
        complete_module = types.ModuleType(module_name)
        lazy_exports()["RaceGauge"] = (module_name, "Gauge")

        class Gauge:
            pass

        complete_module.Gauge = Gauge
        start = threading.Barrier(6)
        results = []
        errors = []

        def import_module(name):
            self.assertEqual(name, module_name)
            return complete_module

        def access_export():
            try:
                start.wait()
                results.append(yr.RaceGauge)
            except Exception as err:
                errors.append(err)

        threads = [threading.Thread(target=access_export) for _ in range(5)]
        with mock.patch.object(yr.importlib, "import_module", side_effect=import_module) as import_mock:
            for thread in threads:
                thread.start()
            start.wait()
            for thread in threads:
                thread.join()

        self.assertEqual([], errors)
        self.assertEqual([Gauge] * 5, results)
        import_mock.assert_any_call(module_name)
        import_count = import_mock.call_count
        self.assertIs(yr.RaceGauge, Gauge)
        self.assertEqual(import_count, import_mock.call_count)

    def test_different_lazy_exports_do_not_hold_lock_while_importing(self):
        modules = {
            "yr.tests.fake_metrics": types.SimpleNamespace(Gauge="gauge"),
            "yr.tests.fake_alarm": types.SimpleNamespace(Alarm="alarm"),
        }
        lazy_exports()["RaceGauge"] = ("yr.tests.fake_metrics", "Gauge")
        lazy_exports()["RaceAlarm"] = ("yr.tests.fake_alarm", "Alarm")
        importing = threading.Barrier(2)
        results = []
        errors = []

        def import_module(name):
            importing.wait(timeout=1)
            module = modules.get(name)
            self.assertIsNotNone(module)
            return module

        def access_export(name):
            try:
                results.append(getattr(yr, name))
            except Exception as err:
                errors.append(err)

        threads = [
            threading.Thread(target=access_export, args=("RaceGauge",)),
            threading.Thread(target=access_export, args=("RaceAlarm",)),
        ]
        with mock.patch.object(yr.importlib, "import_module", side_effect=import_module):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual([], errors)
        self.assertCountEqual(["gauge", "alarm"], results)


if __name__ == "__main__":
    unittest.main()
