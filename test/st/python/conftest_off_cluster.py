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

"""Off-cluster (云外) conftest for openyuanrong SDK testing.

Usage:
    export YR_SERVER_ADDRESS=100.111.54.22:38888
    pytest -s -vv conftest_off_cluster.py::test_connection test_off_cluster.py
"""

import os
import pytest
import yr


def _get_server_address():
    return os.getenv("YR_SERVER_ADDRESS", "")


def _build_conf():
    addr = _get_server_address()
    if not addr:
        raise ValueError("YR_SERVER_ADDRESS env is not set, e.g. export YR_SERVER_ADDRESS=1.2.3.4:38888")
    return yr.Config(
        server_address=addr,
        ds_address=addr,
        in_cluster=False,
        enable_tls=True,
        log_level="DEBUG",
    )


@pytest.fixture(scope="session")
def init_yr():
    """Session-scoped yr init for off-cluster (云外) mode."""
    conf = _build_conf()
    yr.init(conf)
    yield
    yr.finalize()


@pytest.fixture()
def init_yr_per_test():
    """Per-test yr init/finalize for tests that need fresh runtime."""
    conf = _build_conf()
    yr.init(conf)
    yield
    yr.finalize()
