#!/usr/bin/env python3
"""akernel-sdk functional acceptance baseline. The same script must pass for both Python and Rust sandbox backends (A/B).

Covers the full `_SandboxInstance` method surface without explicit bypass flags:
- commands: cmd_run short timeout path plus cmd_start/cmd_poll default polling path and cmd_wait/
  cmd_kill/cmd_list/cmd_send_stdin（background handle）
- files: all eight fs_* operations; shells: bash_* persistent sessions.
- Results use the SDK default inline return path for rootfs instances; yr SDK decides bypass_datasystem by instance type,
  and this script does not override Config.

The only difference from akernel `ensure_yr_init` is transport: the AIO acceptance environment uses HTTP without token,
so yr.init uses enable_tls=False and no auth_token. Product deployments with TLS+token are environment configuration,
apply equally to Python/Rust backends, and do not affect the SDK behavior semantics validated here."""
import asyncio
import os
import sys

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

import yr
import akernel_sdk.sandbox as aks_sandbox

SERVER = os.environ.get("YR_SERVER_ADDRESS", "127.0.0.1:38888")
IMAGE = os.environ.get("YR_SANDBOX_VERIFY_IMAGE", "aio-yr-runtime:latest")

yr.init(yr.Config(server_address=SERVER, enable_tls=False, in_cluster=False, server_name="test"))
aks_sandbox._yr_initialized = True

from akernel_sdk.sandbox_api import Sandbox

results = []
def check(name, cond, detail=""):
    results.append((name, cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail and not cond else ""))


def test_commands(sb):
    r = sb.commands.run("echo hi-akernel")
    check("commands.run basic", "hi-akernel" in r.stdout and r.exit_code == 0, r)
    r = sb.commands.run("pwd", cwd="/tmp")
    check("commands.run cwd", r.stdout.strip() == "/tmp", r)
    r = sb.commands.run("echo $FOO", envs={"FOO": "bar123"})
    check("commands.run envs", "bar123" in r.stdout, r)
    r = sb.commands.run("exit 7")
    check("commands.run exit_code", r.exit_code == 7, r)
    # timeout below the threshold uses the direct cmd_run path, complementing the start/poll path above.
    r = sb.commands.run("echo direct-path", timeout=5)
    check("commands.run direct(cmd_run)", "direct-path" in r.stdout and r.exit_code == 0, r)


def test_commands_background(sb):
    # background + stdin：cmd_start(want_stdin) → cmd_send_stdin(eof) → cmd_wait
    h = sb.commands.run("cat", background=True, stdin=True)
    sb.commands.send_stdin(h.pid, "hello-stdin\n", eof=True)
    r = h.wait(timeout=15)
    check("commands background stdin/wait", "hello-stdin" in r.stdout and r.exit_code == 0, r)
    # cmd_list: background process is visible.
    h2 = sb.commands.run("sleep 30", background=True)
    procs = sb.commands.list()
    check("commands.list shows running", any(p["pid"] == h2.pid and p["running"] for p in procs), procs)
    # cmd_kill: can kill and report the process.
    killed = h2.kill()
    check("commands.kill", killed is True, killed)


def test_files(sb):
    sb.commands.run("mkdir -p /tmp/akt")
    info = sb.files.write("/tmp/akt/a.txt", "hello-fs")
    check("files.write", getattr(info, "path", None) == "/tmp/akt/a.txt", info)
    check("files.read text", sb.files.read("/tmp/akt/a.txt") == "hello-fs")
    blob = bytes([0, 1, 2, 255, 254])
    sb.files.write("/tmp/akt/b.bin", blob)
    check("files.read bytes(hex)", sb.files.read("/tmp/akt/b.bin", format="bytes") == blob)
    check("files.exists true", sb.files.exists("/tmp/akt/a.txt") is True)
    check("files.exists false", sb.files.exists("/tmp/akt/none") is False)
    check("files.make_dir", sb.files.make_dir("/tmp/akt/sub") in (True, None))
    names = [e.name for e in sb.files.list("/tmp/akt")]
    check("files.list", "a.txt" in names and "b.bin" in names, names)
    sb.files.remove("/tmp/akt/a.txt")
    check("files.remove", sb.files.exists("/tmp/akt/a.txt") is False)


async def test_shells(sb):
    sh = await sb.shells.create(cwd="/tmp")
    try:
        out = await sh.run("echo shell-1; echo shell-2")
        text = out if isinstance(out, str) else getattr(out, "stdout", str(out))
        check("shells persistent run", "shell-1" in str(text) and "shell-2" in str(text), text)
        await sh.run("X=persisted")
        out2 = await sh.run("echo $X")
        t2 = out2 if isinstance(out2, str) else getattr(out2, "stdout", str(out2))
        check("shells state persists", "persisted" in str(t2), t2)
    finally:
        sh.close()


def main():
    print(f"[*] create sandbox image={IMAGE}")
    sb = Sandbox(image=IMAGE)
    print(f"[+] id={sb.id}")
    try:
        test_commands(sb)
        test_commands_background(sb)
        test_files(sb)
        asyncio.run(test_shells(sb))
    finally:
        try:
            if hasattr(sb, "kill"):
                sb.kill()
        except Exception as e:
            print(f"[warn] cleanup: {e}")
    n_pass = sum(1 for _, c in results if c)
    print(f"\n=== {n_pass}/{len(results)} passed ===")
    sys.exit(0 if n_pass == len(results) else 1)


if __name__ == "__main__":
    main()
