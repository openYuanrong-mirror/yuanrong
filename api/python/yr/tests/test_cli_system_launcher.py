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

from types import SimpleNamespace
import unittest

from yr.cli.component.base import ComponentConfig
from yr.cli.const import StartMode
from yr.cli.system_launcher import SystemLauncher


class TestCliSystemLauncher(unittest.TestCase):
    def make_launcher(self, name: str):
        return SimpleNamespace(component_config=ComponentConfig(name=name))

    def test_disabled_ds_worker_dependency_is_not_silently_removed(self):
        system_launcher = SystemLauncher.__new__(SystemLauncher)
        system_launcher.mode = StartMode.MASTER
        system_launcher.prepend_char_overrides = {}
        system_launcher.depends_on_overrides = {
            "function_proxy": ["ds_worker", "runtime_launcher"],
        }
        system_launcher.resolver = SimpleNamespace(
            rendered_config={
                "mode": {
                    StartMode.MASTER.value: {
                        "function_proxy": True,
                        "runtime_launcher": True,
                        "ds_worker": False,
                    }
                }
            }
        )

        function_proxy = self.make_launcher("function_proxy")
        runtime_launcher = self.make_launcher("runtime_launcher")
        system_launcher._apply_component_overrides("function_proxy", function_proxy)
        system_launcher.components = {
            "function_proxy": function_proxy,
            "runtime_launcher": runtime_launcher,
        }

        with self.assertRaisesRegex(ValueError, "depends on unknown component 'ds_worker'"):
            system_launcher._get_start_order()

    def test_disabled_etcd_dependency_can_be_provided_externally(self):
        system_launcher = SystemLauncher.__new__(SystemLauncher)
        system_launcher.mode = StartMode.MASTER
        system_launcher.prepend_char_overrides = {}
        system_launcher.depends_on_overrides = {
            "function_master": ["etcd"],
        }
        system_launcher.resolver = SimpleNamespace(
            rendered_config={
                "mode": {
                    StartMode.MASTER.value: {
                        "function_master": True,
                        "etcd": False,
                    }
                }
            }
        )

        function_master = self.make_launcher("function_master")
        system_launcher._apply_component_overrides("function_master", function_master)
        system_launcher.components = {
            "function_master": function_master,
        }

        self.assertEqual(system_launcher._get_start_order(), ["function_master"])


if __name__ == "__main__":
    unittest.main()
