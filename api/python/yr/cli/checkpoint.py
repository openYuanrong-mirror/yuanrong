#!/usr/bin/env python3
# coding=UTF-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class CheckpointClient:
    """Client for checkpoint operations via frontend proxy."""

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port

    def list_by_function_key(
        self,
        tenant_id: str,
        function_type: str,
        namespace: Optional[str] = None,
    ) -> dict:
        body = {
            "requestID": "",
            "functionKey": {
                "tenantID": tenant_id,
                "functionType": function_type,
                "namespace": namespace or "",
            },
        }
        return self._post("/checkpoint/list-by-function-key", body)

    def list_by_tenant(self, tenant_id: str) -> dict:
        body = {"requestID": "", "tenantID": tenant_id}
        return self._post("/checkpoint/list-by-tenant", body)

    def delete(self, checkpoint_id: str) -> dict:
        body = {"requestID": "", "checkpointID": checkpoint_id}
        return self._post("/checkpoint/delete", body)

    def _post(self, path: str, body: dict) -> dict:
        url = f"https://{self._host}:{self._port}{path}"
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(url, json=body)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            return {"code": 1, "message": str(e)}
        except httpx.HTTPError as e:
            return {"code": 1, "message": str(e)}
        except Exception as e:
            return {"code": 1, "message": str(e)}


def get_frontend_address_from_session(session_file: Path) -> Optional[tuple[str, int]]:
    """Extract frontend address from session file.

    Returns tuple of (frontend_ip, frontend_port) or None if not available.
    """
    if not session_file.exists():
        return None
    try:
        with session_file.open() as f:
            session = json.load(f)
        cluster_info = session.get("cluster_info", {}).get("for-join", {})
        frontend_port = cluster_info.get("frontend.port")
        function_master_ip = cluster_info.get("function_master.ip")
        if frontend_port and function_master_ip:
            return function_master_ip, int(frontend_port)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to read session file: {e}")
    return None
