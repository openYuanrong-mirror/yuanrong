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
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""CLI implementation for executing code in a sandboxed environment."""

import asyncio
import os
import shlex
import signal
import shutil
import ssl
import sys
import tarfile
import tempfile
import termios
import tty
from pathlib import Path
from urllib.parse import quote

import websockets


def create_ssl_context(
    cert_file=None,
    key_file=None,
    ca_file=None,
    verify_server=True,
    quiet=False
):
    """Create SSL context for mutual TLS authentication.
    
    Args:
        cert_file: Client certificate file path
        key_file: Client private key file path
        ca_file: CA certificate file path for server verification
        verify_server: Whether to verify server certificate
    
    Returns:
        ssl.SSLContext or None if TLS is not configured
    """
    # If no certificates are provided and verification is enabled, let
    # websockets build the default TLS context for wss:// URLs.
    if not cert_file and not key_file and not ca_file and verify_server:
        return None
    
    try:
        # Create SSL context
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        
        # Load client certificate and key for mutual authentication
        if cert_file and key_file:
            if not os.path.exists(cert_file):
                if not quiet:
                    print(f"Warning: Client certificate file not found: {cert_file}", file=sys.stderr)
            elif not os.path.exists(key_file):
                if not quiet:
                    print(f"Warning: Client key file not found: {key_file}", file=sys.stderr)
            else:
                ssl_context.load_cert_chain(cert_file, key_file)
        
        # Load CA certificate for server verification
        if ca_file:
            if not os.path.exists(ca_file):
                if not quiet:
                    print(f"Warning: CA certificate file not found: {ca_file}", file=sys.stderr)
            else:
                ssl_context.load_verify_locations(ca_file)
        else:
            # Use default system CA certificates
            ssl_context.load_default_certs()
        
        # Configure server certificate verification
        if not verify_server:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            if not quiet:
                print("Warning: Server certificate verification is disabled (insecure)", file=sys.stderr)
        
        return ssl_context
    except Exception as e:
        if not quiet:
            print(f"Error creating SSL context: {e}", file=sys.stderr)
        return None


class RawTerminal:
    def __init__(self, fd):
        self.fd = fd
        self.old = None

    def __enter__(self):
        self.old = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.old:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)


async def read_stdin(ws, should_exit, quiet=False):
    """读取标准输入并发送到 WebSocket"""
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader(loop=loop)
    protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
    try:
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    except Exception as e:
        if not quiet:
            print(f"Warning: failed to attach stdin pipe: {e}", file=sys.stderr)
        return

    try:
        while not should_exit.is_set():
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=0.1)
                if not data:
                    break
                # 检测 Ctrl+] (ASCII 29) 作为退出信号
                if b"\x1d" in data:
                    should_exit.set()
                    break
                await ws.send(data)
            except asyncio.TimeoutError:
                continue
    except Exception:
        pass
    finally:
        pass


async def heartbeat_loop(ws, should_exit, ping_interval=30, ping_timeout=10, quiet=False):
    """定期发送 WebSocket ping，超时则退出。"""
    while not should_exit.is_set():
        await asyncio.sleep(ping_interval)
        if should_exit.is_set():
            return
        try:
            pong = await ws.ping()
            await asyncio.wait_for(pong, timeout=ping_timeout)
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            if not quiet:
                print("\r\n[Connection lost: heartbeat timeout]", file=sys.stderr)
            should_exit.set()
            return


async def read_websocket(ws, should_exit, quiet=False):
    """从 WebSocket 读取输出并写入标准输出"""
    try:
        async for message in ws:
            if should_exit.is_set():
                break
            text = message if isinstance(message, str) else message.decode("utf-8", errors="replace")
            if quiet and text.strip() == "[Process exited]":
                should_exit.set()
                break
            os.write(sys.stdout.fileno(), text.encode("utf-8"))
    except Exception:
        pass
    finally:
        should_exit.set()


async def watch_terminal_resize(ws, should_exit):
    """监听本地终端尺寸变化并发送 resize 消息到 WebSocket"""
    if not hasattr(signal, "SIGWINCH"):
        return

    loop = asyncio.get_running_loop()
    resize_event = asyncio.Event()

    def on_resize(_signum, _frame):
        loop.call_soon_threadsafe(resize_event.set)

    try:
        old_handler = signal.getsignal(signal.SIGWINCH)
        signal.signal(signal.SIGWINCH, on_resize)
    except Exception:
        return

    last_size = None
    try:
        while not should_exit.is_set():
            try:
                await asyncio.wait_for(resize_event.wait(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            resize_event.clear()
            try:
                terminal_size = shutil.get_terminal_size()
            except Exception:
                continue

            cols = terminal_size.columns
            rows = terminal_size.lines
            if cols <= 0 or rows <= 0:
                continue

            current_size = (cols, rows)
            if current_size == last_size:
                continue

            last_size = current_size
            try:
                await ws.send(f"RESIZE:{cols}:{rows}")
            except Exception:
                should_exit.set()
                break
    finally:
        try:
            signal.signal(signal.SIGWINCH, old_handler)
        except Exception:
            pass


async def send_terminal_resize(ws, rows=None, cols=None):
    """发送终端尺寸到 WebSocket（协议: RESIZE:cols:rows）"""
    try:
        if rows is None or cols is None:
            terminal_size = shutil.get_terminal_size()
            if rows is None:
                rows = terminal_size.lines
            if cols is None:
                cols = terminal_size.columns
    except Exception:
        return

    if rows and cols and rows > 0 and cols > 0:
        try:
            await ws.send(f"RESIZE:{cols}:{rows}")
        except Exception:
            pass


def build_exec_uri(
    host, port, instance=None, command=None, tty=None, rows=None, cols=None, user=None, token=None, use_ssl=False
):
    """Build exec websocket URI."""
    query_params = []
    if instance:
        query_params.append(f"instance={quote(instance)}")
    if command:
        query_params.append(f"command={quote(command)}")
    if tty is not None:
        query_params.append(f"tty={str(tty).lower()}")
    if rows:
        query_params.append(f"rows={rows}")
    if cols:
        query_params.append(f"cols={cols}")
    if user:
        query_params.append(f"tenant_id={quote(user)}")
    if token:
        query_params.append(f"token={quote(token)}")

    query_string = "&".join(query_params)
    protocol = "wss" if use_ssl else "ws"
    uri = f"{protocol}://{host}:{port}/terminal/ws"
    if query_string:
        uri += f"?{query_string}"
    return uri


def build_exec_ssl_context(
    use_ssl=False, cert_file=None, key_file=None, ca_file=None, verify_server=True, quiet=False
):
    """Build SSL context for exec websocket when TLS is enabled."""
    if not use_ssl:
        return None
    return create_ssl_context(
        cert_file=cert_file,
        key_file=key_file,
        ca_file=ca_file,
        verify_server=verify_server,
        quiet=quiet,
    )


async def _drain_websocket(ws, should_exit, quiet=False, writer=None):
    """Read websocket messages until the process exits or the socket closes."""
    try:
        async for message in ws:
            if should_exit.is_set():
                break
            if isinstance(message, str):
                if quiet and message.strip() == "[Process exited]":
                    should_exit.set()
                    break
                if writer is not None:
                    writer.write(message.encode("utf-8"))
                continue

            if writer is not None:
                writer.write(message)
    except Exception:
        pass
    finally:
        should_exit.set()


def _create_tar_archive(source_path: Path, root_name: str) -> str:
    """Create a tar archive for a file or directory and return the temp path."""
    archive_file = tempfile.NamedTemporaryFile(suffix=".tar", delete=False)
    archive_file.close()
    with tarfile.open(archive_file.name, mode="w:") as archive:
        archive.add(str(source_path), arcname=root_name)
    return archive_file.name


def _restore_from_tar(archive_path: str, local_path: str) -> None:
    """Restore a tar stream into the requested local path."""
    target = Path(local_path)
    target_parent = target.parent
    target_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as unpack_dir:
        unpack_root = Path(unpack_dir)
        with tarfile.open(archive_path, mode="r:") as archive:
            archive.extractall(unpack_root)

        entries = list(unpack_root.iterdir())
        if len(entries) != 1:
            raise RuntimeError("unexpected archive layout: expected a single top-level entry")
        source_root = entries[0]

        if source_root.is_dir():
            if target.exists():
                if not target.is_dir():
                    raise RuntimeError(f"cannot overwrite non-directory target: {target}")
                shutil.copytree(source_root, target, dirs_exist_ok=True)
                return
            shutil.move(str(source_root), str(target))
            return

        target_parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.is_dir():
                raise RuntimeError(f"cannot overwrite directory target with file: {target}")
            target.unlink()
        shutil.move(str(source_root), str(target))


async def copy_to_remote(
    host,
    port,
    instance,
    local_path,
    remote_path,
    user=None,
    use_ssl=False,
    cert_file=None,
    key_file=None,
    ca_file=None,
    verify_server=True,
    token=None,
):
    """Upload a local file into an instance via the exec websocket."""
    source = Path(local_path)
    archive_path = _create_tar_archive(source, Path(remote_path).name)
    archive_size = Path(archive_path).stat().st_size
    remote_arg = shlex.quote(remote_path)
    size_arg = shlex.quote(str(archive_size))
    command = (
        "sh -c 'mkdir -p \"$(dirname \"$1\")\" && "
        "head -c \"$2\" | tar -xmf - -C \"$(dirname \"$1\")\"' "
        f"sh {remote_arg} {size_arg}"
    )
    uri = build_exec_uri(
        host,
        port,
        instance=instance,
        command=command,
        tty=False,
        user=user,
        token=token,
        use_ssl=use_ssl,
    )
    ssl_context = build_exec_ssl_context(
        use_ssl=use_ssl,
        cert_file=cert_file,
        key_file=key_file,
        ca_file=ca_file,
        verify_server=verify_server,
        quiet=True,
    )

    try:
        async with websockets.connect(uri, ssl=ssl_context) as ws:
            should_exit = asyncio.Event()
            tasks = [
                asyncio.create_task(_drain_websocket(ws, should_exit, quiet=True)),
                asyncio.create_task(heartbeat_loop(ws, should_exit)),
            ]
            try:
                with open(archive_path, "rb") as file_obj:
                    while True:
                        chunk = file_obj.read(64 * 1024)
                        if not chunk:
                            break
                        await ws.send(chunk)
                await should_exit.wait()
            finally:
                for task in tasks:
                    if task.done():
                        continue
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
    finally:
        Path(archive_path).unlink(missing_ok=True)


async def copy_from_remote(
    host,
    port,
    instance,
    remote_path,
    local_path,
    user=None,
    use_ssl=False,
    cert_file=None,
    key_file=None,
    ca_file=None,
    verify_server=True,
    token=None,
):
    """Download a file from an instance via the exec websocket."""
    command = (
        "sh -c 'tar -cf - -C \"$(dirname \"$1\")\" \"$(basename \"$1\")\"' "
        f"sh {shlex.quote(remote_path)}"
    )
    uri = build_exec_uri(
        host,
        port,
        instance=instance,
        command=command,
        tty=False,
        user=user,
        token=token,
        use_ssl=use_ssl,
    )
    ssl_context = build_exec_ssl_context(
        use_ssl=use_ssl,
        cert_file=cert_file,
        key_file=key_file,
        ca_file=ca_file,
        verify_server=verify_server,
        quiet=True,
    )

    archive_file = tempfile.NamedTemporaryFile(suffix=".tar", delete=False)
    archive_file.close()
    try:
        async with websockets.connect(uri, ssl=ssl_context) as ws:
            should_exit = asyncio.Event()
            with open(archive_file.name, "wb") as file_obj:
                tasks = [
                    asyncio.create_task(_drain_websocket(ws, should_exit, quiet=True, writer=file_obj)),
                    asyncio.create_task(heartbeat_loop(ws, should_exit)),
                ]
                try:
                    await should_exit.wait()
                finally:
                    for task in tasks:
                        if task.done():
                            continue
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

        _restore_from_tar(archive_file.name, local_path)
    finally:
        Path(archive_file.name).unlink(missing_ok=True)


async def run_client(
    host, port, instance=None, command=None, tty=None, stdin=None, rows=None, cols=None, user=None,
    use_ssl=False, cert_file=None, key_file=None, ca_file=None, verify_server=True, token=None, quiet=False
):
    # 获取当前终端的实际尺寸作为默认值
    if rows is None or cols is None:
        try:
            terminal_size = shutil.get_terminal_size()
            if rows is None:
                rows = terminal_size.lines
            if cols is None:
                cols = terminal_size.columns
        except Exception:
            # 如果无法获取，使用服务端默认值
            pass

    uri = build_exec_uri(
        host,
        port,
        instance=instance,
        command=command,
        tty=tty,
        rows=rows,
        cols=cols,
        user=user,
        token=token,
        use_ssl=use_ssl,
    )

    if tty:
        if instance:
            print(f"Connecting to {instance}...\nPress Ctrl+] to disconnect", file=sys.stderr)
        else:
            print("Connecting...\nPress Ctrl+] to disconnect", file=sys.stderr)
    
    # Create SSL context if needed
    ssl_context = build_exec_ssl_context(
        use_ssl=use_ssl,
        cert_file=cert_file,
        key_file=key_file,
        ca_file=ca_file,
        verify_server=verify_server,
        quiet=quiet,
    )
    if use_ssl:
        if ssl_context and tty:
            print("Using mutual TLS authentication", file=sys.stderr)
        elif not ssl_context and tty:
            print("Warning: SSL requested but failed to create SSL context", file=sys.stderr)

    try:
        async with websockets.connect(uri, ssl=ssl_context) as ws:
            should_exit = asyncio.Event()

            interactive = tty and sys.stdin.isatty()

            if tty:
                await send_terminal_resize(ws, rows=rows, cols=cols)

            if interactive:
                raw_term = RawTerminal(sys.stdin.fileno())
                raw_term.__enter__()

            try:
                # 同时处理输入和输出
                tasks = [
                    asyncio.create_task(read_websocket(ws, should_exit, quiet=quiet)),
                    asyncio.create_task(heartbeat_loop(ws, should_exit, quiet=quiet)),
                ]
                if stdin or interactive:
                    tasks.append(asyncio.create_task(read_stdin(ws, should_exit, quiet=quiet)))
                if interactive:
                    tasks.append(asyncio.create_task(watch_terminal_resize(ws, should_exit)))

                await should_exit.wait()

                # 结束后取消所有后台任务
                for task in tasks:
                    if task.done():
                        continue
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            finally:
                if interactive:
                    raw_term.__exit__(None, None, None)
    except KeyboardInterrupt:
        if not quiet:
            print("\n[Interrupted]", file=sys.stderr)
    except Exception as e:
        if not quiet:
            print(f"\nConnection error: {e}", file=sys.stderr)
