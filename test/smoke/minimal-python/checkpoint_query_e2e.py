#!/usr/bin/env python3

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Optional

import httpx


REPO_ROOT = Path(__file__).resolve().parents[3]
PROTO_DIR = REPO_ROOT / "functionsystem" / "proto" / "posix"
ETCD_ENDPOINT = os.environ.get(
    "YR_CHECKPOINT_ETCD_ENDPOINT", "https://127.0.0.1:32379"
)
SNAP_MANAGER_ENDPOINT = os.environ.get(
    "YR_SNAP_MANAGER_ENDPOINT", "https://127.0.0.1:22770/snap-manager"
)
SNAPSHOT_KEY_PREFIX = "/yr/snapshot/"


def require_protoc() -> str:
    protoc = shutil.which("protoc") or "/opt/buildtools/bin/protoc"
    if not Path(protoc).exists():
        raise RuntimeError(f"protoc not found: {protoc}")
    return protoc


def compile_proto_modules(tmpdir: str):
    protoc = require_protoc()
    protos = sorted(str(path.name) for path in PROTO_DIR.glob("*.proto"))
    subprocess.run(
        [protoc, f"-I{PROTO_DIR}", f"--python_out={tmpdir}", *protos],
        check=True,
        cwd=PROTO_DIR,
    )
    os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
    sys.path.insert(0, tmpdir)
    import message_pb2  # type: ignore

    return message_pb2


def http_post(url: str, body: bytes, headers: Optional[Dict[str, str]] = None) -> bytes:
    _headers = {"Content-Type": "application/json"}
    if headers:
        _headers.update(headers)
    with httpx.Client(timeout=10) as client:
        return client.post(url, content=body, headers=_headers).content


def etcd_put(key: str, value: bytes) -> None:
    payload = {
        "key": base64.b64encode(key.encode("utf-8")).decode("ascii"),
        "value": base64.b64encode(value).decode("ascii"),
    }
    http_post(
        f"{ETCD_ENDPOINT}/v3/kv/put",
        json.dumps(payload).encode("utf-8"),
        {"Content-Type": "application/json"},
    )


def etcd_delete(key: str) -> None:
    payload = {"key": base64.b64encode(key.encode("utf-8")).decode("ascii")}
    http_post(
        f"{ETCD_ENDPOINT}/v3/kv/deleterange",
        json.dumps(payload).encode("utf-8"),
        {"Content-Type": "application/json"},
    )


def parse_binary_response(message_cls, path: str, request_body: bytes):
    raw = http_post(
        f"{SNAP_MANAGER_ENDPOINT}{path}",
        request_body,
        {"Content-Type": "application/octet-stream", "Type": "proto"},
    )
    message = message_cls()
    message.ParseFromString(raw)
    return message


def wait_until(fetch_fn, expected_ids: list[str], timeout_s: float = 10.0):
    deadline = time.time() + timeout_s
    last_ids = None
    while time.time() < deadline:
        rsp = fetch_fn()
        last_ids = list(rsp.checkpointIDs)
        if last_ids == expected_ids:
            return rsp
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {expected_ids}, last={last_ids}")


def make_snapshot(
    message_pb2,
    snapshot_id: str,
    tenant_id: str,
    function_type: str,
    namespace: str,
    create_time: int,
):
    meta = message_pb2.SnapshotMetadata()
    meta.instanceInfo.instanceID = f"inst-{snapshot_id}"
    meta.instanceInfo.requestID = f"req-{snapshot_id}"
    meta.instanceInfo.runtimeID = "runtime-smoke"
    meta.instanceInfo.runtimeAddress = "127.0.0.1:1"
    meta.instanceInfo.functionAgentID = "agent-smoke"
    meta.instanceInfo.functionProxyID = "proxy-smoke"
    meta.instanceInfo.function = function_type
    meta.instanceInfo.tenantID = tenant_id
    meta.snapshotInfo.checkpointID = snapshot_id
    meta.snapshotInfo.storage = "sfs://checkpoint-query-e2e"
    meta.snapshotInfo.size = 128
    meta.snapshotInfo.createTime = str(create_time)
    meta.snapshotInfo.ttlSeconds = 3600
    meta.functionKey.tenantID = tenant_id
    meta.functionKey.functionType = function_type
    meta.functionKey.namespace = namespace
    return meta


def main() -> int:
    run_id = str(int(time.time()))
    tenant_a = f"e2e-tenant-a-{run_id}"
    tenant_b = f"e2e-tenant-b-{run_id}"
    func_counter = "smoke.Counter"
    func_other = "smoke.Other"

    injected_keys: list[str] = []

    with tempfile.TemporaryDirectory(prefix="checkpoint-query-pb-") as tmpdir:
        message_pb2 = compile_proto_modules(tmpdir)

        snapshots = [
            make_snapshot(message_pb2, f"{run_id}-cp-1", tenant_a, func_counter, "ns-a", 1001),
            make_snapshot(message_pb2, f"{run_id}-cp-2", tenant_a, func_counter, "ns-a", 1002),
            make_snapshot(message_pb2, f"{run_id}-cp-3", tenant_a, func_counter, "ns-b", 1003),
            make_snapshot(message_pb2, f"{run_id}-cp-4", tenant_a, func_other, "ns-a", 1004),
            make_snapshot(message_pb2, f"{run_id}-cp-5", tenant_b, func_counter, "ns-a", 1005),
        ]

        try:
            for meta in snapshots:
                key = SNAPSHOT_KEY_PREFIX + meta.snapshotInfo.checkpointID
                etcd_put(key, meta.SerializeToString())
                injected_keys.append(key)

            def list_by_function_key(tenant_id: str, function_type: str, namespace: str):
                req = message_pb2.ListSnapshotsByFunctionKeyRequest()
                req.requestID = f"req-fk-{tenant_id}-{function_type}-{namespace or 'all'}"
                req.functionKey.tenantID = tenant_id
                req.functionKey.functionType = function_type
                req.functionKey.namespace = namespace
                return parse_binary_response(
                    message_pb2.ListSnapshotsByFunctionKeyResponse,
                    "/list-snapshots-by-function-key",
                    req.SerializeToString(),
                )

            def list_by_tenant(tenant_id: str):
                req = message_pb2.ListSnapshotsByTenantRequest()
                req.requestID = f"req-tenant-{tenant_id}"
                req.tenantID = tenant_id
                return parse_binary_response(
                    message_pb2.ListSnapshotsByTenantResponse,
                    "/list-snapshots-by-tenant",
                    req.SerializeToString(),
                )

            rsp_func_ns_a = wait_until(
                lambda: list_by_function_key(tenant_a, func_counter, "ns-a"),
                [f"{run_id}-cp-1", f"{run_id}-cp-2"],
            )
            rsp_func_all_ns = wait_until(
                lambda: list_by_function_key(tenant_a, func_counter, ""),
                [f"{run_id}-cp-1", f"{run_id}-cp-2", f"{run_id}-cp-3"],
            )
            rsp_tenant_a = wait_until(
                lambda: list_by_tenant(tenant_a),
                [f"{run_id}-cp-1", f"{run_id}-cp-2", f"{run_id}-cp-3", f"{run_id}-cp-4"],
            )
            rsp_tenant_b = wait_until(
                lambda: list_by_tenant(tenant_b),
                [f"{run_id}-cp-5"],
            )

            assert rsp_func_ns_a.code == 0, rsp_func_ns_a
            assert rsp_func_all_ns.code == 0, rsp_func_all_ns
            assert rsp_tenant_a.code == 0, rsp_tenant_a
            assert rsp_tenant_b.code == 0, rsp_tenant_b

            summary = {
                "status": "ok",
                "tenantA": tenant_a,
                "tenantB": tenant_b,
                "functionType": func_counter,
                "functionKeyNsA": list(rsp_func_ns_a.checkpointIDs),
                "functionKeyAllNs": list(rsp_func_all_ns.checkpointIDs),
                "tenantAList": list(rsp_tenant_a.checkpointIDs),
                "tenantBList": list(rsp_tenant_b.checkpointIDs),
            }
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0
        finally:
            for key in injected_keys:
                try:
                    etcd_delete(key)
                except OSError:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
