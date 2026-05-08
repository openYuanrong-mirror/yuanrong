#!/usr/bin/env python3
# coding=UTF-8
#
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

import os

import yr


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    server_address = os.environ["YR_SERVER_ADDRESS"]
    timeout = int(os.getenv("YR_K8S_SMOKE_TIMEOUT", "180"))
    conf = yr.Config(
        server_address=server_address,
        ds_address=server_address,
        in_cluster=False,
        enable_tls=env_bool("YR_ENABLE_TLS", False),
        log_level=os.getenv("YR_LOG_LEVEL", "INFO"),
        auth_token=os.getenv("YR_JWT_TOKEN", ""),
    )

    yr.init(conf)
    try:
        ref = yr.put(42)
        assert yr.get(ref, timeout=timeout) == 42
        print("SMOKE put/get ok", flush=True)

        @yr.invoke
        def add(left, right):
            return left + right

        assert yr.get(add.invoke(20, 22), timeout=timeout) == 42
        print("SMOKE remote invoke ok", flush=True)
    finally:
        yr.finalize()


if __name__ == "__main__":
    main()
