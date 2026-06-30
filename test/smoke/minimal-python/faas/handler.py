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

import os


def handler(event, context):
    mode = os.environ.get("YR_RUNTIME_MODE", "unknown")
    function_name = os.environ.get("YR_FUNCTION_NAME", "unknown")
    instance_id = os.environ.get("YR_INSTANCE_ID", "unknown")

    if isinstance(event, dict):
        command = event.get("command")
        if command == "env":
            return {
                "ok": True,
                "echo": f"mode={mode},func={function_name}",
                "mode": "env",
                "function_name": function_name,
                "instance_id": instance_id,
            }
        if command == "repeat":
            return {"ok": True, "echo": "repeat", "mode": "text"}
        if "text" in event:
            return {"ok": True, "echo": event["text"], "mode": "text"}
        return {"ok": True, "echo": event.get("name", "unknown"), "mode": "json"}

    if isinstance(event, str):
        return {"ok": True, "echo": event, "mode": "text"}

    return {"ok": False, "echo": "unsupported payload type", "mode": "error"}
