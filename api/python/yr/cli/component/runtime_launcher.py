#!/usr/bin/env python3
# coding=UTF-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

import logging
from pathlib import Path

from yr.cli.component.base import ComponentLauncher

logger = logging.getLogger(__name__)


class RuntimeLauncherLauncher(ComponentLauncher):
    def prestart_hook(self) -> None:
        socket_path = Path(self.resolver.rendered_config[self.name]["args"]["socket"])
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        socket_path.unlink(missing_ok=True)

    def health_check(self) -> bool:
        socket_path = Path(self.resolver.rendered_config[self.name]["health_check"]["endpoint"])
        if socket_path.is_socket():
            return True
        logger.error("%s: runtime-launcher socket is not ready: %s", self.name, socket_path)
        return False
