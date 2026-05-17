#!/usr/bin/env python3
"""End-to-end test for the full checkpoint lifecycle via the Python SDK APIs.

Tests the complete flow through yr SDK:
  1. Create instance → snapshot → verify checkpoint_id property
  2. SDK list: ins.list_checkpoints(), Counter.list_checkpoints(),
     yr.list_checkpoints(Counter), yr.list_checkpoints()
  3. SDK restore: ins.snapstart(), yr.restore_from_checkpoint()
     - verify restored instance state, checkpoint_id, snapstart_info
  4. SDK delete: ins.delete_checkpoint(), yr.delete_checkpoint()
     - verify checkpoint removed from list after each delete

Requires a running yr cluster (runtime + functionsystem + datasystem).

Environment variables:
  YR_SMOKE_SERVER_ADDRESS     runtime server   (default: 127.0.0.1:22773)
  YR_SMOKE_DS_ADDRESS         datasystem       (default: 127.0.0.1:31501)
  YR_CHECKPOINT_TENANT_ID     tenant           (default: default)
  YR_CHECKPOINT_PROGRESS_FILE progress json    (default: /tmp/checkpoint_sdk_lifecycle_progress.json)
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import yr
from yr.config import Config
from yr.checkpoint import SnapstartInfo

TENANT_ID = os.environ.get("YR_CHECKPOINT_TENANT_ID", "default")
PROGRESS_FILE = os.environ.get(
    "YR_CHECKPOINT_PROGRESS_FILE",
    os.path.join(tempfile.gettempdir(), "checkpoint_sdk_lifecycle_progress.json"),
)


def mark(stage: str, **kwargs) -> None:
    payload = {"stage": stage, "ts": time.time(), **kwargs}
    Path(PROGRESS_FILE).write_text(json.dumps(payload, sort_keys=True))
    print(f"  [{stage}] {kwargs}" if kwargs else f"  [{stage}]")


def wait_until_list(fetch_fn, expected_ids, timeout_s=15.0):
    """Poll fetch_fn() until result matches expected_ids (sorted)."""
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = fetch_fn()
        if sorted(last) == sorted(expected_ids):
            return last
        time.sleep(0.3)
    raise AssertionError(f"timed out waiting for {expected_ids}, last={last}")


def wait_until_not_in_list(fetch_fn, excluded_id, timeout_s=15.0):
    """Poll fetch_fn() until excluded_id is no longer in the result list."""
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = fetch_fn()
        if excluded_id not in last:
            return last
        time.sleep(0.3)
    raise AssertionError(f"timed out: {excluded_id} still in {last}")


# ---------------------------------------------------------------------------
# Instance class
# ---------------------------------------------------------------------------

@yr.instance
class Counter:
    def __init__(self, start=0):
        self.value = start

    def add(self, n):
        self.value += n
        return self.value

    def get(self):
        return self.value


# ---------------------------------------------------------------------------
# Test phases
# ---------------------------------------------------------------------------

def phase_snapshot(ins):
    """Create a snapshot and verify the checkpoint_id property."""
    print("\n=== Phase 1: Snapshot ===")
    assert ins.checkpoint_id is None, f"expected None before snapshot, got {ins.checkpoint_id}"

    ckpt_id = ins.snapshot(leave_running=True)
    assert ckpt_id, "snapshot() returned empty checkpoint_id"
    assert ins.checkpoint_id == ckpt_id, (
        f"checkpoint_id property mismatch: {ins.checkpoint_id} != {ckpt_id}"
    )
    mark("snapshot_ok", checkpoint_id=ckpt_id)
    return ckpt_id


def phase_sdk_list(ins, ckpt_id):
    """Verify all SDK list variants see the checkpoint."""
    print("\n=== Phase 2: SDK List ===")

    print("  ins.list_checkpoints() ...")
    result = wait_until_list(lambda: ins.list_checkpoints(), [ckpt_id])
    mark("ins_list_ok", result=result)

    print("  Counter.list_checkpoints() ...")
    result = wait_until_list(lambda: Counter.list_checkpoints(), [ckpt_id])
    mark("class_list_ok", result=result)

    print("  yr.list_checkpoints(Counter) ...")
    result = wait_until_list(lambda: yr.list_checkpoints(Counter), [ckpt_id])
    mark("yr_list_class_ok", result=result)

    print("  yr.list_checkpoints() ...")
    result = wait_until_list(
        lambda: yr.list_checkpoints(),
        [ckpt_id],
    )
    mark("yr_list_tenant_ok", result=result)


def phase_restore_via_instance(ins, ckpt_id, expected_value):
    """Restore via ins.snapstart() and verify state."""
    print("\n=== Phase 3a: Restore via ins.snapstart() ===")
    restored = ins.snapstart(ckpt_id)
    assert restored is not None, "snapstart() returned None"
    assert restored.instance_id, "restored instance has no instance_id"

    assert restored.checkpoint_id == ckpt_id, (
        f"restored checkpoint_id mismatch: {restored.checkpoint_id} != {ckpt_id}"
    )
    assert restored.snapstart_info is not None, "snapstart_info is None"
    assert isinstance(restored.snapstart_info, SnapstartInfo), (
        f"snapstart_info type mismatch: {type(restored.snapstart_info)}"
    )

    val = yr.get(restored.get.invoke())
    assert val == expected_value, f"restored state mismatch: {val} != {expected_value}"
    mark("ins_snapstart_ok",
         instance_id=restored.instance_id,
         restored_value=val,
         snapstart_info_route=restored.snapstart_info.route_address)
    return restored


def phase_restore_via_global(ckpt_id, expected_value):
    """Restore via yr.restore_from_checkpoint() and verify state."""
    print("\n=== Phase 3b: Restore via yr.restore_from_checkpoint() ===")
    restored = yr.restore_from_checkpoint(ckpt_id, Counter)
    assert restored is not None, "restore_from_checkpoint() returned None"
    assert restored.instance_id, "restored instance has no instance_id"

    assert restored.checkpoint_id == ckpt_id, (
        f"restored checkpoint_id mismatch: {restored.checkpoint_id} != {ckpt_id}"
    )
    assert restored.snapstart_info is not None, "snapstart_info is None"

    val = yr.get(restored.get.invoke())
    assert val == expected_value, f"restored state mismatch: {val} != {expected_value}"
    mark("yr_restore_ok",
         instance_id=restored.instance_id,
         restored_value=val)
    return restored


def phase_delete_via_instance(ins, ckpt_id):
    """Delete via ins.delete_checkpoint() and verify it's gone."""
    print("\n=== Phase 4a: Delete via ins.delete_checkpoint() ===")
    ins.delete_checkpoint()
    assert ins.checkpoint_id is None, (
        f"checkpoint_id should be None after delete, got {ins.checkpoint_id}"
    )
    mark("ins_delete_ok", deleted=ckpt_id)

    print("  verify deleted from yr.list_checkpoints(Counter) ...")
    wait_until_not_in_list(lambda: yr.list_checkpoints(Counter), ckpt_id)
    mark("ins_delete_verified")


def phase_delete_via_global(ckpt_id):
    """Delete via yr.delete_checkpoint() and verify it's gone."""
    print("\n=== Phase 4b: Delete via yr.delete_checkpoint() ===")
    yr.delete_checkpoint(ckpt_id)
    mark("yr_delete_ok", deleted=ckpt_id)

    print("  verify deleted from yr.list_checkpoints(Counter) ...")
    wait_until_not_in_list(lambda: yr.list_checkpoints(Counter), ckpt_id)
    mark("yr_delete_verified")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # server = os.environ.get("YR_SMOKE_SERVER_ADDRESS", "127.0.0.1:22773")
    # ds_addr = os.environ.get("YR_SMOKE_DS_ADDRESS", "127.0.0.1:31501")
    # conf = Config(server_address=server, is_driver=True, auto=False)
    # conf.ds_address = ds_addr
    # conf.in_cluster = True
    # conf.tenant_id = TENANT_ID

    try:
        mark("before_init")
        # yr.init(conf)
        yr.init()
        mark("after_init")

        # --- Create instance and set initial state ---
        print("\n=== Phase 0: Create instance ===")
        ins = Counter.invoke(10)
        yr.get(ins.add.invoke(5))  # value = 15
        val = yr.get(ins.get.invoke())
        assert val == 15, f"initial state wrong: {val}"
        mark("instance_ready", instance_id=ins.instance_id, value=val)

        # --- Phase 1: snapshot ---
        ckpt_1 = phase_snapshot(ins)

        # --- Phase 2: SDK list ---
        phase_sdk_list(ins, ckpt_1)

        # --- Phase 3a: restore via ins.snapstart ---
        restored_a = phase_restore_via_instance(ins, ckpt_1, expected_value=15)

        # --- Phase 3b: restore via yr.restore_from_checkpoint ---
        restored_b = phase_restore_via_global(ckpt_1, expected_value=15)

        # Cleanup restored instances
        yr.get(restored_a.add.invoke(0))  # keep alive until we're done verifying
        yr.get(restored_b.add.invoke(0))

        # --- Phase 4a: delete ckpt_1 via ins.delete_checkpoint ---
        # First take a second snapshot so we can test yr.delete_checkpoint too
        print("\n=== Create second snapshot for delete test ===")
        ckpt_2 = ins.snapshot(leave_running=True)
        assert ckpt_2, "second snapshot() returned empty"
        assert ckpt_2 != ckpt_1, "second checkpoint should differ from first"
        mark("snapshot_2_ok", checkpoint_id=ckpt_2)

        # Now we have ckpt_1 and ckpt_2 in the list
        print("  verify both checkpoints in list ...")
        wait_until_list(lambda: yr.list_checkpoints(Counter), [ckpt_1, ckpt_2])

        # Delete ckpt_1 via instance (uses stored _checkpoint_id = ckpt_2)
        # We need to explicitly pass ckpt_1 since ins._checkpoint_id is now ckpt_2
        print("\n=== Phase 4a: Delete ckpt_1 via ins.delete_checkpoint(ckpt_1) ===")
        ins.delete_checkpoint(ckpt_1)
        mark("ins_delete_explicit_ok", deleted=ckpt_1)

        print("  verify ckpt_1 deleted ...")
        wait_until_not_in_list(lambda: yr.list_checkpoints(Counter), ckpt_1)
        mark("ins_delete_explicit_verified")

        # --- Phase 4b: delete ckpt_2 via yr.delete_checkpoint ---
        phase_delete_via_global(ckpt_2)

        # --- Phase 5: verify all gone ---
        print("\n=== Phase 5: Final verification ===")
        final = yr.list_checkpoints(Counter)
        assert ckpt_1 not in final, f"ckpt_1 still present: {final}"
        assert ckpt_2 not in final, f"ckpt_2 still present: {final}"
        mark("final_ok", remaining=final)

        summary = {
            "status": "ok",
            "tenant": TENANT_ID,
            "ckpt_1": ckpt_1,
            "ckpt_2": ckpt_2,
            "restore_via_ins": restored_a.instance_id,
            "restore_via_yr": restored_b.instance_id,
        }
        print(f"\n{json.dumps(summary, indent=2, sort_keys=True)}")
        return 0

    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    finally:
        mark("cleanup")
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception as _e:
            print(f"[warn] flush error: {_e}", file=sys.stderr)


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        os._exit(code)
