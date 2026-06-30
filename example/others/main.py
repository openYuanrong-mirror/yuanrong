#!/usr/bin/env python3
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

import logging
from datetime import datetime, timezone

import yr


logging.basicConfig(level=logging.INFO, format="%(message)s")
LOGGER = logging.getLogger(__name__)


@yr.instance
class Counter:
    @staticmethod
    def get():
        return 1


conf = yr.Config()
conf.log_level = "DEBUG"
conf.in_cluster = False
yr.init(conf)

for _ in range(10):
    t1 = datetime.now(timezone.utc)
    c = Counter.invoke()
    yr.get(c.get.invoke())
    t2 = datetime.now(timezone.utc)

    diff_ms = (t2 - t1).total_seconds() * 1000
    LOGGER.info("create elapsed: %.1f ms", diff_ms)

    t1 = datetime.now(timezone.utc)
    yr.get(c.get.invoke())
    t2 = datetime.now(timezone.utc)

    diff_ms = (t2 - t1).total_seconds() * 1000
    LOGGER.info("invoke elapsed: %.1f ms", diff_ms)
    c.terminate()
