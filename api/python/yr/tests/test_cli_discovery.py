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

import unittest

from yr.cli.discovery import _merge_discovered_overrides


class TestCliDiscovery(unittest.TestCase):
    def test_explicit_override_wins_over_discovery_default(self):
        explicit = (
            'ds_worker.args.master_address="10.250.0.10:12123"',
            'values.host_ip="10.250.0.11"',
        )
        discovered = (
            "values.function_master.ip='10.250.0.10'",
            "ds_worker.args.master_address=''",
        )

        self.assertEqual(
            _merge_discovered_overrides(explicit, discovered),
            (
                'ds_worker.args.master_address="10.250.0.10:12123"',
                'values.host_ip="10.250.0.11"',
                "values.function_master.ip='10.250.0.10'",
            ),
        )

    def test_discovery_default_is_kept_without_explicit_value(self):
        self.assertEqual(
            _merge_discovered_overrides((), ("ds_worker.args.master_address=''",)),
            ("ds_worker.args.master_address=''",),
        )


if __name__ == "__main__":
    unittest.main()
