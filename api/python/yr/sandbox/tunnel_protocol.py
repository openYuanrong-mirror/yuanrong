# api/python/yr/sandbox/tunnel_protocol.py
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
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Wire protocol frames for the sandbox reverse tunnel."""
import base64
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Dict


_HTTP_METHOD_RE = re.compile(r"^[A-Z]+$")
_DEFAULT_MAX_BODY_SIZE = 256 << 20   # 256 MB
_DEFAULT_MAX_FRAME_SIZE = 384 << 20  # Allows 256 MB base64 bodies plus JSON overhead.
_CRLF_RE = re.compile(r"[\r\n]")
_PATH_TRAVERSAL_RE = re.compile(r"(?:^|/)\.\.(?:/|$)")


def _read_size_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


MAX_TUNNEL_BODY_SIZE = _read_size_env("YR_TUNNEL_MAX_BODY_SIZE", _DEFAULT_MAX_BODY_SIZE)
MAX_TUNNEL_FRAME_SIZE = _read_size_env("YR_TUNNEL_MAX_FRAME_SIZE", _DEFAULT_MAX_FRAME_SIZE)
_MAX_BODY_SIZE = MAX_TUNNEL_BODY_SIZE
_MAX_FRAME_SIZE = MAX_TUNNEL_FRAME_SIZE


def _validate_path(path: str) -> str:
    if not isinstance(path, str):
        raise ValueError("path must be a string")
    if _PATH_TRAVERSAL_RE.search(path):
        raise ValueError(f"Path traversal not allowed: {path!r}")
    return path


def _validate_headers(headers: Dict[str, str]) -> Dict[str, str]:
    for k, v in headers.items():
        if _CRLF_RE.search(v):
            raise ValueError(f"CRLF in header value for key {k!r}")
    return headers


def make_id() -> str:
    """Generate a unique frame ID."""
    return str(uuid.uuid4())


def _decode_body(data: dict) -> bytes:
    body = data.get("body")
    if body in (None, ""):
        return b""
    if not isinstance(body, str):
        raise ValueError("body must be a base64 string or null")
    decoded = base64.b64decode(body, validate=True)
    if len(decoded) > _MAX_BODY_SIZE:
        raise ValueError(f"Body exceeds {_MAX_BODY_SIZE} bytes limit")
    return decoded


def _validate_http_method(method: str) -> str:
    if not isinstance(method, str) or not _HTTP_METHOD_RE.fullmatch(method):
        raise ValueError(f"Invalid HTTP method: {method!r}")
    return method


def _validate_http_status(status: int) -> int:
    if not isinstance(status, int) or not (100 <= status <= 599):
        raise ValueError(f"Invalid HTTP status: {status!r}")
    return status


def _validate_ws_close_code(code: int) -> int:
    if not isinstance(code, int) or not (1000 <= code <= 4999):
        raise ValueError(f"Invalid WebSocket close code: {code!r}")
    return code


@dataclass
class HttpReqFrame:
    id: str
    method: str
    path: str
    headers: Dict[str, str]
    body: bytes
    type: str = field(default="http_req", init=False)

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type, "id": self.id, "method": self.method,
            "path": self.path, "headers": self.headers,
            "body": base64.b64encode(self.body).decode(),
        })


@dataclass
class HttpRespFrame:
    id: str
    status: int
    headers: Dict[str, str]
    body: bytes
    type: str = field(default="http_resp", init=False)

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type, "id": self.id, "status": self.status,
            "headers": self.headers,
            "body": base64.b64encode(self.body).decode(),
        })


@dataclass
class WsConnectFrame:
    id: str
    path: str
    headers: Dict[str, str]
    type: str = field(default="ws_connect", init=False)

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "id": self.id, "path": self.path, "headers": self.headers})


@dataclass
class WsConnectedFrame:
    id: str
    type: str = field(default="ws_connected", init=False)

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "id": self.id})


@dataclass
class WsMessageFrame:
    id: str
    data: str
    binary: bool = False
    type: str = field(default="ws_message", init=False)

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "id": self.id, "data": self.data, "binary": self.binary})


@dataclass
class WsCloseFrame:
    id: str
    code: int = 1000
    reason: str = ""
    type: str = field(default="ws_close", init=False)

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "id": self.id, "code": self.code, "reason": self.reason})


@dataclass
class ErrorFrame:
    id: str
    message: str
    type: str = field(default="error", init=False)

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "id": self.id, "message": self.message})


@dataclass
class PingFrame:
    id: str
    timestamp: float
    type: str = field(default="ping", init=False)

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "id": self.id, "timestamp": self.timestamp})


@dataclass
class PongFrame:
    id: str
    timestamp: float
    type: str = field(default="pong", init=False)

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "id": self.id, "timestamp": self.timestamp})


def parse_frame(raw: str):
    """Parse a JSON frame string into the appropriate frame dataclass."""
    if len(raw) > _MAX_FRAME_SIZE:
        raise ValueError(f"Frame exceeds {_MAX_FRAME_SIZE} bytes limit")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Frame must be a JSON object")
    t = data.get("type")
    if t == "http_req":
        return HttpReqFrame(
            id=data["id"], method=_validate_http_method(data["method"]),
            path=_validate_path(data["path"]),
            headers=_validate_headers(data.get("headers", {})),
            body=_decode_body(data),
        )
    if t == "http_resp":
        return HttpRespFrame(
            id=data["id"], status=_validate_http_status(data["status"]),
            headers=_validate_headers(data.get("headers", {})),
            body=_decode_body(data),
        )
    if t == "ws_connect":
        return WsConnectFrame(
            id=data["id"], path=_validate_path(data["path"]),
            headers=_validate_headers(data.get("headers", {})),
        )
    if t == "ws_connected":
        return WsConnectedFrame(id=data["id"])
    if t == "ws_message":
        return WsMessageFrame(id=data["id"], data=data["data"], binary=data.get("binary", False))
    if t == "ws_close":
        return WsCloseFrame(
            id=data["id"],
            code=_validate_ws_close_code(data.get("code", 1000)),
            reason=data.get("reason", ""),
        )
    if t == "error":
        return ErrorFrame(id=data["id"], message=data["message"])
    if t == "ping":
        return PingFrame(id=data["id"], timestamp=data["timestamp"])
    if t == "pong":
        return PongFrame(id=data["id"], timestamp=data["timestamp"])
    raise ValueError(f"Unknown frame type: {t!r}")
