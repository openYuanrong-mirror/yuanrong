#!/usr/bin/env python3

import base64
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import yr
from yr.config import Config
from yr.common import utils
from yr.decorator.instance_proxy import InstanceProxy


REPO_ROOT = Path(__file__).resolve().parents[3]
PROTO_DIR = REPO_ROOT / "functionsystem" / "proto" / "posix"
ETCD_ENDPOINT = os.environ.get(
    "YR_CHECKPOINT_ETCD_ENDPOINT", "https://127.0.0.1:32379"
)
TENANT_ID = os.environ.get("YR_CHECKPOINT_TENANT_ID", "default")
PROGRESS_FILE = os.environ.get("YR_CHECKPOINT_PROGRESS_FILE", os.path.join(tempfile.gettempdir(), "checkpoint_actor_query_progress.json"))


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
    sys.path.insert(0, tmpdir)
    import message_pb2  # type: ignore

    return message_pb2


def http_post(url: str, body: bytes) -> bytes:
    with httpx.Client(timeout=10) as client:
        return client.post(url, content=body, headers={"Content-Type": "application/json"}).content


def etcd_put(key: str, value: bytes) -> None:
    body = json.dumps(
        {
            "key": base64.b64encode(key.encode()).decode(),
            "value": base64.b64encode(value).decode(),
        }
    ).encode()
    http_post(f"{ETCD_ENDPOINT}/v3/kv/put", body)


def etcd_delete(key: str) -> None:
    body = json.dumps({"key": base64.b64encode(key.encode()).decode()}).encode()
    http_post(f"{ETCD_ENDPOINT}/v3/kv/deleterange", body)


def wait_until(fetch_fn, expected, timeout_s=10.0):
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = fetch_fn()
        if last == expected:
            return last
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {expected}, last={last}")


def mark(stage: str, **kwargs) -> None:
    payload = {"stage": stage, **kwargs}
    Path(PROGRESS_FILE).write_text(json.dumps(payload, sort_keys=True))


@yr.instance
class Counter:
    def __init__(self, start):
        self.value = start

    def add(self, n):
        self.value += n
        return self.value

    def get(self):
        return self.value


def main() -> int:
    server = os.environ.get("YR_SMOKE_SERVER_ADDRESS", "127.0.0.1:22773")
    ds_addr = os.environ.get("YR_SMOKE_DS_ADDRESS", "127.0.0.1:31501")
    conf = Config(server_address=server, is_driver=True, auto=False)
    conf.ds_address = ds_addr
    conf.in_cluster = True
    conf.tenant_id = TENANT_ID

    injected_keys = []
    result = {}
    try:
        mark("before_init")
        yr.init(conf)
        mark("after_init", tenantID=TENANT_ID)
        counter_cls = Counter.get_original_cls()
        class_descriptor = utils.ObjectDescriptor.get_from_class(counter_cls)
        class_methods = dict(inspect.getmembers(counter_cls, utils.is_function_or_method))
        ins = InstanceProxy(
            instance_id="checkpoint-query-proxy",
            class_descriptor=class_descriptor,
            class_methods=class_methods,
            base_cls=inspect.getmro(counter_cls),
            function_id="",
            need_order=True,
            namespace="",
        )
        function_type = f"{class_descriptor.module_name}.{class_descriptor.class_name}"
        mark("proxy_ready", functionType=function_type, tenantID=TENANT_ID)

        with tempfile.TemporaryDirectory(prefix="checkpoint-actor-pb-") as tmpdir:
            message_pb2 = compile_proto_modules(tmpdir)
            checkpoints = [
                ("cp-actor-a", "ns-a", 1001),
                ("cp-actor-b", "ns-a", 1002),
                ("cp-actor-c", "ns-b", 1003),
            ]
            for checkpoint_id, namespace, create_time in checkpoints:
                meta = message_pb2.SnapshotMetadata()
                meta.instanceInfo.instanceID = f"inst-{checkpoint_id}"
                meta.instanceInfo.requestID = f"req-{checkpoint_id}"
                meta.instanceInfo.runtimeID = "runtime-actor-e2e"
                meta.instanceInfo.runtimeAddress = "127.0.0.1:1"
                meta.instanceInfo.functionAgentID = "agent-actor-e2e"
                meta.instanceInfo.functionProxyID = "proxy-actor-e2e"
                meta.instanceInfo.function = function_type
                meta.instanceInfo.tenantID = TENANT_ID
                meta.snapshotInfo.checkpointID = checkpoint_id
                meta.snapshotInfo.storage = "sfs://checkpoint-actor-query-e2e"
                meta.snapshotInfo.size = 256
                meta.snapshotInfo.createTime = str(create_time)
                meta.snapshotInfo.ttlSeconds = 3600
                meta.functionKey.tenantID = TENANT_ID
                meta.functionKey.functionType = function_type
                meta.functionKey.namespace = namespace
                key = f"/yr/snapshot/{checkpoint_id}"
                etcd_put(key, meta.SerializeToString())
                injected_keys.append(key)
        mark("snapshots_injected", checkpointCount=len(injected_keys))

        list_ns_a = wait_until(lambda: ins.list_checkpoints("ns-a"), ["cp-actor-a", "cp-actor-b"])
        mark("instance_list_ns_a_ok", result=list_ns_a)
        list_all = wait_until(lambda: ins.list_checkpoints(), ["cp-actor-a", "cp-actor-b", "cp-actor-c"])
        mark("instance_list_all_ok", result=list_all)
        global_list = wait_until(lambda: yr.list_checkpoints(Counter), ["cp-actor-a", "cp-actor-b", "cp-actor-c"])
        mark("global_class_list_ok", result=global_list)
        tenant_list = wait_until(lambda: yr.list_checkpoints(), ["cp-actor-a", "cp-actor-b", "cp-actor-c"])
        mark("tenant_list_ok", result=tenant_list)

        result = {
            "status": "ok",
            "tenantID": TENANT_ID,
            "functionType": function_type,
            "instanceListNsA": list_ns_a,
            "instanceListAll": list_all,
            "globalClassList": global_list,
            "globalTenantList": tenant_list,
        }
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        sys.stdout.flush()
        return 0
    finally:
        for key in injected_keys:
            try:
                etcd_delete(key)
            except Exception:
                pass
        mark("cleanup_done", cleaned=len(injected_keys))
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        os._exit(code)
