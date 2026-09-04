#!/usr/bin/env python3
# coding=UTF-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

from pathlib import Path

from yr.cli.component.base import ComponentLauncher


class DataPlaneGatewayLauncher(ComponentLauncher):
    """Launcher shared by the standalone Edge and Node gateway processes."""

    def prestart_hook(self) -> None:
        env = self.resolver.rendered_config[self.name]["env"]
        log_dir = env.get("YR_DATA_PLANE_LOG_DIR", "")
        if log_dir:
            Path(log_dir).mkdir(parents=True, exist_ok=True, mode=0o750)
        if self.name == "node_proxy":
            uds_dir = env.get("YR_DATA_PLANE_NODE_PROXY_ACTIVITY_UDS_DIR", "")
            if uds_dir:
                Path(uds_dir).mkdir(parents=True, exist_ok=True, mode=0o750)

    def health_check(self) -> bool:
        return self._check_http_or_https_health()
