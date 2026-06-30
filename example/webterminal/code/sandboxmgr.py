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
import os

import yr


logging.basicConfig(level=logging.INFO, format="%(message)s")
LOGGER = logging.getLogger(__name__)


@yr.instance
class MockSandbox:
    @staticmethod
    def hello():
        return os.environ.get("INSTANCE_ID")


def init(ctx):
    return


def create():
    LOGGER.info("create %s", yr.__file__)
    opt = yr.InvokeOptions()
    opt.custom_extensions["lifecycle"] = "detached"
    opt.idle_timeout = 60 * 60 * 24 * 10

    sandbox = MockSandbox.options(opt).invoke()
    instance = yr.get(sandbox.hello.invoke())
    LOGGER.info("sandbox created, name=%s", instance)
    return instance


def delete(instance_name):
    yr.kill_instance(instance_name)


def handler(event, ctx):
    cfg = yr.Config()
    cfg.log_level = "DEBUG"
    cfg.function_id = "sn:cn:yrk:default:function:0-defaultservice-py39:$latest"
    yr.init(cfg)
    try:
        if event.get("action") == "create":
            instance_name = create()
            return {"instance": instance_name}
        elif event.get("action") == "delete":
            instance_name = event.get("instance")
            if instance_name:
                delete(instance_name)
                return {"message": f"Instance {instance_name} deleted successfully"}
            else:
                return {"error": "Instance name is required for deletion"}
    except Exception as e:
        return {"error": str(e)}
    return {"error": f"unknown action: {event.get('action')}"}
