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

"""E2E validation: InstanceProxy.real_id property"""

import logging

import yr

LOGGER = logging.getLogger(__name__)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


@yr.instance
class Counter:
    def __init__(self):
        self.count = 0

    def inc(self):
        self.count += 1
        return self.count


def main():
    yr.init()
    try:
        ins = Counter.invoke()

        logic_id = ins.instance_id
        real_id = ins.real_id

        LOGGER.info("logic_id : %s", logic_id)
        LOGGER.info("real_id  : %s", real_id)

        require(isinstance(real_id, str) and len(real_id) > 0, "real_id should be a non-empty string")
        LOGGER.info("real_id type/length check passed")

        result = yr.get(ins.inc.invoke())
        require(result == 1, f"expected 1, got {result}")
        LOGGER.info("actor method invoke passed: count=%s", result)

        ins.terminate()
        LOGGER.info("PASS: InstanceProxy.real_id e2e validation succeeded")
    finally:
        yr.finalize()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    main()
