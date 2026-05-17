#!/usr/bin/env python3
"""End-to-end test for the full checkpoint management lifecycle.

Covers the new interfaces added in the snapshot management commit:
  - Inject snapshots into etcd
  - List by function key / tenant via snap-manager (protobuf)
  - List by function key / tenant via frontend (JSON)
  - Delete via snap-manager (protobuf)
  - Delete via frontend (JSON)
  - Verify deletion from both list endpoints

Environment variables:
  YR_CHECKPOINT_ETCD_ENDPOINT      etcd HTTPS API      (default: https://127.0.0.1:32379)
  YR_SNAP_MANAGER_ENDPOINT         snap-manager base   (default: https://127.0.0.1:22770/snap-manager)
  YR_FRONTEND_ENDPOINT             frontend base       (default: https://127.0.0.1:8888)
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

import httpx


REPO_ROOT = Path(__file__).resolve().parents[3]
PROTO_DIR = REPO_ROOT / "functionsystem" / "proto" / "posix"
ETCD_ENDPOINT = os.environ.get(
    "YR_CHECKPOINT_ETCD_ENDPOINT", "https://127.0.0.1:32379"
)
SNAP_MANAGER_ENDPOINT = os.environ.get(
    "YR_SNAP_MANAGER_ENDPOINT", "https://127.0.0.1:22770/snap-manager"
)
FRONTEND_ENDPOINT = os.environ.get(
    "YR_FRONTEND_ENDPOINT", "https://127.0.0.1:8888"
)
SNAPSHOT_KEY_PREFIX = "/yr/snapshot/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def require_protoc() -> str:
    protoc = shutil.which("protoc") or "/opt/buildtools/bin/protoc"
    if not Path(protoc).exists():
        raise RuntimeError(f"protoc not found: {protoc}")
    return protoc


def compile_proto_modules(tmpdir: str):
    protoc = require_protoc()
    protos = sorted(str(p.name) for p in PROTO_DIR.glob("*.proto"))
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
    with httpx.Client(timeout=15) as client:
        return client.post(url, content=body, headers=_headers).content


def http_post_json(url: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    try:
        return json.loads(http_post(url, data).decode("utf-8"))
    except json.JSONDecodeError as exc:
        return {"code": 1, "message": str(exc)}


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


def parse_pb_response(message_cls, path: str, request_body: bytes):
    raw = http_post(
        f"{SNAP_MANAGER_ENDPOINT}{path}",
        request_body,
        {"Content-Type": "application/octet-stream", "Type": "proto"},
    )
    msg = message_cls()
    msg.ParseFromString(raw)
    return msg


def wait_until(fetch_fn, check_fn, timeout_s: float = 10.0):
    """Poll fetch_fn() until check_fn(result) is True."""
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = fetch_fn()
        if check_fn(last):
            return last
        time.sleep(0.3)
    raise AssertionError(f"timed out, last result: {last}")


def wait_until_ids(fetch_fn, expected_ids: List[str], timeout_s: float = 10.0):
    """Poll until the returned checkpoint IDs match expected_ids exactly."""
    deadline = time.time() + timeout_s
    last_ids = None
    while time.time() < deadline:
        rsp = fetch_fn()
        last_ids = list(rsp.checkpointIDs)
        if sorted(last_ids) == sorted(expected_ids):
            return rsp
        time.sleep(0.3)
    raise AssertionError(f"timed out waiting for {expected_ids}, last={last_ids}")


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------

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
    meta.instanceInfo.runtimeID = "runtime-lifecycle-e2e"
    meta.instanceInfo.runtimeAddress = "127.0.0.1:1"
    meta.instanceInfo.functionAgentID = "agent-lifecycle-e2e"
    meta.instanceInfo.functionProxyID = "proxy-lifecycle-e2e"
    meta.instanceInfo.function = function_type
    meta.instanceInfo.tenantID = tenant_id
    meta.snapshotInfo.checkpointID = snapshot_id
    meta.snapshotInfo.storage = "sfs://checkpoint-lifecycle-e2e"
    meta.snapshotInfo.size = 256
    meta.snapshotInfo.createTime = str(create_time)
    meta.snapshotInfo.ttlSeconds = 3600
    meta.functionKey.tenantID = tenant_id
    meta.functionKey.functionType = function_type
    meta.functionKey.namespace = namespace
    return meta


# ---------------------------------------------------------------------------
# Protobuf snap-manager helpers
# ---------------------------------------------------------------------------

def pb_list_by_function_key(message_pb2, tenant_id, function_type, namespace):
    req = message_pb2.ListSnapshotsByFunctionKeyRequest()
    req.requestID = f"req-fk-{tenant_id}-{function_type}-{namespace or 'all'}"
    req.functionKey.tenantID = tenant_id
    req.functionKey.functionType = function_type
    req.functionKey.namespace = namespace
    return parse_pb_response(
        message_pb2.ListSnapshotsByFunctionKeyResponse,
        "/list-snapshots-by-function-key",
        req.SerializeToString(),
    )


def pb_list_by_tenant(message_pb2, tenant_id):
    req = message_pb2.ListSnapshotsByTenantRequest()
    req.requestID = f"req-tenant-{tenant_id}"
    req.tenantID = tenant_id
    return parse_pb_response(
        message_pb2.ListSnapshotsByTenantResponse,
        "/list-snapshots-by-tenant",
        req.SerializeToString(),
    )


def pb_delete(message_pb2, checkpoint_id):
    req = message_pb2.DeleteSnapshotRequest()
    req.requestID = f"req-del-{checkpoint_id}"
    req.checkpointID = checkpoint_id
    return parse_pb_response(
        message_pb2.DeleteSnapshotResponse,
        "/delete-snapshot",
        req.SerializeToString(),
    )


# ---------------------------------------------------------------------------
# Frontend JSON helpers
# ---------------------------------------------------------------------------

def fe_list_by_function_key(tenant_id, function_type, namespace=""):
    return http_post_json(
        f"{FRONTEND_ENDPOINT}/checkpoint/list-by-function-key",
        {
            "requestID": "",
            "functionKey": {
                "tenantID": tenant_id,
                "functionType": function_type,
                "namespace": namespace,
            },
        },
    )


def fe_list_by_tenant(tenant_id):
    return http_post_json(
        f"{FRONTEND_ENDPOINT}/checkpoint/list-by-tenant",
        {"requestID": "", "tenantID": tenant_id},
    )


def fe_delete(checkpoint_id):
    return http_post_json(
        f"{FRONTEND_ENDPOINT}/checkpoint/delete",
        {"requestID": "", "checkpointID": checkpoint_id},
    )


# ---------------------------------------------------------------------------
# Test phases
# ---------------------------------------------------------------------------

def phase_inject(message_pb2, run_id, tenant, func_type):
    """Inject 3 test snapshots into etcd and return (snapshot_ids, etcd_keys)."""
    specs = [
        (f"{run_id}-lc-1", "ns-a", 2001),
        (f"{run_id}-lc-2", "ns-a", 2002),
        (f"{run_id}-lc-3", "ns-b", 2003),
    ]
    ids = []
    keys = []
    for sid, ns, ts in specs:
        meta = make_snapshot(message_pb2, sid, tenant, func_type, ns, ts)
        key = SNAPSHOT_KEY_PREFIX + sid
        etcd_put(key, meta.SerializeToString())
        ids.append(sid)
        keys.append(key)
    return ids, keys


def phase_list_snap_manager(message_pb2, tenant, func_type, expected_ids):
    """Verify list via protobuf snap-manager endpoints."""
    print("[snap-manager] list-by-function-key (ns-a) ...")
    rsp = wait_until_ids(
        lambda: pb_list_by_function_key(message_pb2, tenant, func_type, "ns-a"),
        [eid for eid in expected_ids if eid.endswith("-lc-1") or eid.endswith("-lc-2")],
    )
    assert rsp.code == 0, f"list-by-function-key failed: {rsp}"
    print(f"  ok: {list(rsp.checkpointIDs)}")

    print("[snap-manager] list-by-function-key (all namespaces) ...")
    rsp = wait_until_ids(
        lambda: pb_list_by_function_key(message_pb2, tenant, func_type, ""),
        expected_ids,
    )
    assert rsp.code == 0, f"list-by-function-key failed: {rsp}"
    print(f"  ok: {list(rsp.checkpointIDs)}")

    print("[snap-manager] list-by-tenant ...")
    rsp = wait_until_ids(
        lambda: pb_list_by_tenant(message_pb2, tenant),
        expected_ids,
    )
    assert rsp.code == 0, f"list-by-tenant failed: {rsp}"
    print(f"  ok: {list(rsp.checkpointIDs)}")


def phase_list_frontend(tenant, func_type, expected_ids):
    """Verify list via frontend JSON endpoints."""
    print("[frontend] /checkpoint/list-by-function-key (all namespaces) ...")
    rsp = wait_until(
        lambda: fe_list_by_function_key(tenant, func_type),
        lambda r: sorted(r.get("checkpointIDs", [])) == sorted(expected_ids),
    )
    print(f"  ok: {rsp.get('checkpointIDs')}")

    print("[frontend] /checkpoint/list-by-tenant ...")
    rsp = wait_until(
        lambda: fe_list_by_tenant(tenant),
        lambda r: sorted(r.get("checkpointIDs", [])) == sorted(expected_ids),
    )
    print(f"  ok: {rsp.get('checkpointIDs')}")


def phase_delete_via_snap_manager(message_pb2, delete_id, tenant, func_type, remaining_ids):
    """Delete one checkpoint via snap-manager and verify it's gone."""
    print(f"[snap-manager] delete {delete_id} ...")
    rsp = pb_delete(message_pb2, delete_id)
    assert rsp.code == 0, f"delete failed: {rsp}"
    print(f"  delete ok")

    print("[snap-manager] verify deleted from list-by-function-key ...")
    wait_until_ids(
        lambda: pb_list_by_function_key(message_pb2, tenant, func_type, ""),
        remaining_ids,
    )
    print(f"  ok: {remaining_ids}")

    print("[snap-manager] verify deleted from list-by-tenant ...")
    wait_until_ids(
        lambda: pb_list_by_tenant(message_pb2, tenant),
        remaining_ids,
    )
    print(f"  ok: {remaining_ids}")


def phase_delete_via_frontend(delete_id, tenant, func_type, remaining_ids):
    """Delete one checkpoint via frontend and verify it's gone."""
    print(f"[frontend] /checkpoint/delete {delete_id} ...")
    rsp = fe_delete(delete_id)
    assert rsp.get("code", 1) == 0, f"frontend delete failed: {rsp}"
    print(f"  delete ok")

    print("[frontend] verify deleted from /checkpoint/list-by-function-key ...")
    wait_until(
        lambda: fe_list_by_function_key(tenant, func_type),
        lambda r: delete_id not in r.get("checkpointIDs", [delete_id]),
    )
    print(f"  ok: remaining={remaining_ids}")

    print("[frontend] verify deleted from /checkpoint/list-by-tenant ...")
    wait_until(
        lambda: fe_list_by_tenant(tenant),
        lambda r: delete_id not in r.get("checkpointIDs", [delete_id]),
    )
    print(f"  ok: remaining={remaining_ids}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    run_id = str(int(time.time()))
    tenant = f"e2e-lifecycle-{run_id}"
    func_type = "lifecycle_e2e.Counter"

    injected_keys: list = []

    with tempfile.TemporaryDirectory(prefix="checkpoint-lifecycle-pb-") as tmpdir:
        message_pb2 = compile_proto_modules(tmpdir)

        try:
            # --- Phase 1: inject test data ---
            print(f"=== Phase 1: Inject snapshots (tenant={tenant}) ===")
            snapshot_ids, injected_keys = phase_inject(
                message_pb2, run_id, tenant, func_type,
            )
            print(f"  injected: {snapshot_ids}")

            # --- Phase 2: list via snap-manager ---
            print("\n=== Phase 2: List via snap-manager (protobuf) ===")
            phase_list_snap_manager(message_pb2, tenant, func_type, snapshot_ids)

            # --- Phase 3: list via frontend ---
            print("\n=== Phase 3: List via frontend (JSON) ===")
            phase_list_frontend(tenant, func_type, snapshot_ids)

            # --- Phase 4: delete via snap-manager ---
            delete_sm_id = snapshot_ids[0]  # delete lc-1
            remaining_after_sm = snapshot_ids[1:]
            print(f"\n=== Phase 4: Delete via snap-manager ({delete_sm_id}) ===")
            phase_delete_via_snap_manager(
                message_pb2, delete_sm_id, tenant, func_type, remaining_after_sm,
            )

            # --- Phase 5: delete via frontend ---
            delete_fe_id = snapshot_ids[1]  # delete lc-2
            remaining_after_fe = [snapshot_ids[2]]
            print(f"\n=== Phase 5: Delete via frontend ({delete_fe_id}) ===")
            phase_delete_via_frontend(
                delete_fe_id, tenant, func_type, remaining_after_fe,
            )

            # --- Phase 6: final verification ---
            print("\n=== Phase 6: Final verification ===")
            print("[snap-manager] list-by-tenant should have 1 checkpoint ...")
            rsp = wait_until_ids(
                lambda: pb_list_by_tenant(message_pb2, tenant),
                remaining_after_fe,
            )
            assert rsp.code == 0
            print(f"  ok: {list(rsp.checkpointIDs)}")

            print("[frontend] list-by-tenant should have 1 checkpoint ...")
            rsp = wait_until(
                lambda: fe_list_by_tenant(tenant),
                lambda r: sorted(r.get("checkpointIDs", [])) == sorted(remaining_after_fe),
            )
            print(f"  ok: {rsp.get('checkpointIDs')}")

            summary = {
                "status": "ok",
                "tenant": tenant,
                "functionType": func_type,
                "injected": snapshot_ids,
                "deletedViaSnapManager": delete_sm_id,
                "deletedViaFrontend": delete_fe_id,
                "remaining": remaining_after_fe,
            }
            print(f"\n{json.dumps(summary, indent=2, sort_keys=True)}")
            return 0

        except Exception as e:
            print(f"\nFAILED: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

        finally:
            for key in injected_keys:
                try:
                    etcd_delete(key)
                except Exception:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
