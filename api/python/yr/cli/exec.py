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
import math
import os
import shlex
import signal
import shutil
import ssl
import sys
import tarfile
import tempfile
import termios
import threading
import tty
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import quote

import websockets

# ── Auto cp-mode selection ────────────────────────────────────────────────────

# Extensions that are already compressed or otherwise incompressible.
_INCOMPRESSIBLE_EXTS = frozenset({
    ".gz", ".bz2", ".xz", ".lz4", ".zst", ".zip", ".7z", ".rar",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff",
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".mp3", ".ogg", ".flac", ".aac", ".wav",
    ".pdf",
})

# Extensions that are typically highly compressible (text / source code).
_COMPRESSIBLE_EXTS = frozenset({
    ".txt", ".log", ".csv", ".tsv",
    ".py", ".js", ".ts", ".go", ".cpp", ".c", ".h", ".hpp", ".java",
    ".rs", ".rb", ".php", ".sh", ".bash", ".zsh",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".html", ".htm", ".css",
    ".md", ".rst", ".tex",
    ".conf", ".cfg", ".ini", ".env",
    ".sql",
})

# Shannon entropy threshold (bits/byte, 0-8).  Values above this suggest the
# content is already compressed or random, making gzip compression ineffective.
# Calibrated from measurements: random urandom ≈ 7.997, source/log ≈ 4-5.
_ENTROPY_INCOMPRESSIBLE = 7.2

# Files below this size are dominated by connection/exec overhead (~300 ms),
# so the compression saving is negligible regardless of file type.
_SIZE_SMALL = 256 * 1024          # 256 KB

# Upload: run_in_executor threading cost (~5-8 ms/chunk) means only extremely
# high compression ratios (>50x) can outweigh the overhead on a fast exec-stdin
# channel.  Lower-compression files (source code ~5x) are better served by
# non-streaming; users on slow networks can always override with --streaming.
_UPLOAD_RATIO_MIN = 50            # compression ratio threshold for upload streaming

# Download: exec-channel stdout is the bottleneck (~3.5 MB/s regardless of
# network speed), so ANY meaningful compression (>2x) translates directly to
# faster transfers.
_DOWNLOAD_RATIO_MIN = 2.0         # compression ratio threshold for download streaming


@dataclass
class ExecConnection:
    host: str
    port: str
    user: str = None
    use_ssl: bool = False
    cert_file: str = None
    key_file: str = None
    ca_file: str = None
    verify_server: bool = True
    token: str = None
    quiet: bool = False


@dataclass
class ExecInvocation:
    instance: str = None
    command: Any = None
    allocate_tty: bool = None
    stdin: bool = None
    rows: int = None
    cols: int = None


@dataclass
class CopyRequest:
    instance: str
    local_path: str
    remote_path: str


def _quiet_connection(connection: ExecConnection) -> ExecConnection:
    return replace(connection, quiet=True)


def _sample_entropy(path: str, sample_bytes: int = 65536) -> float:
    """Return Shannon entropy (bits/byte) of the first *sample_bytes* of *path*.

    Complexity: O(sample_bytes) ≈ 1 ms for 64 KB.
    Returns a value in [0, 8]; values close to 8 indicate incompressible data.
    """
    freq = [0] * 256
    with open(path, "rb") as fh:
        data = fh.read(sample_bytes)
    for byte in data:
        freq[byte] += 1
    total = len(data)
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in freq:
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def _sample_compression_ratio(path: str, sample_bytes: int = 65536) -> float:
    """Return the gzip compression ratio of the first *sample_bytes* of *path*.

    Complexity: O(sample_bytes) ≈ 0.3-1 ms for 64 KB (gzip level 1 default).
    Returns ratio = original / compressed.  Values close to 1.0 mean the data
    is incompressible; values >> 1 mean high compression benefit.

    Unlike Shannon entropy, this directly measures gzip effectiveness, which is
    what matters for choosing between streaming and non-streaming transfer.
    """
    import gzip as _gzip
    with open(path, "rb") as fh:
        data = fh.read(sample_bytes)
    if not data:
        return 1.0
    compressed = _gzip.compress(data, compresslevel=1)
    return len(data) / max(len(compressed), 1)


def _dir_stats(path: str, sample_bytes: int = 65536) -> tuple:
    """Return (total_size, compression_ratio) for a directory.

    Walks the directory tree to compute the total file size.  Then collects up
    to *sample_bytes* of content from the largest files (largest files tend to
    dominate transfer time) to estimate the representative compression ratio.

    Complexity: O(number of directory entries) for the walk + O(sample_bytes)
    for the gzip probe.
    """
    import gzip as _gzip

    # Gather all regular files sorted by size descending.
    file_sizes: list[tuple[int, str]] = []
    for dirpath, _, filenames in os.walk(path):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                file_sizes.append((os.path.getsize(fpath), fpath))
            except OSError:
                pass
    total_size = sum(sz for sz, _ in file_sizes)

    # Sample bytes from the largest files to estimate compression ratio.
    file_sizes.sort(reverse=True)
    sample_data = bytearray()
    for _, fpath in file_sizes:
        if len(sample_data) >= sample_bytes:
            break
        try:
            with open(fpath, "rb") as fh:
                sample_data += fh.read(sample_bytes - len(sample_data))
        except OSError:
            pass

    if not sample_data:
        return total_size, 1.0
    compressed = _gzip.compress(bytes(sample_data), compresslevel=1)
    ratio = len(sample_data) / max(len(compressed), 1)
    return total_size, ratio


def choose_cp_mode(local_path: str, remote_path: str, upload: bool) -> bool:
    """Auto-select transfer mode for ``yrcli cp``.

    Returns ``True`` (streaming) or ``False`` (non-streaming).

    Upload decision (local file is accessible):
      For files:
        1. Small (<256 KB)               → non-streaming (RTT overhead dominates).
        2. Known incompressible extension → non-streaming (skip sampling).
        3. High entropy (>7.2 bits/byte) → non-streaming (random/binary data).
        4. Compression ratio < 50x       → non-streaming.
           (run_in_executor threading cost ~5-8 ms/chunk only pays off when the
           compressed size is tiny, i.e. for extremely repetitive data like logs.)
        5. Otherwise                     → streaming.
      For directories:
        - Compute total content size via os.walk.
        - Sample up to 64 KB from the largest files as a gzip probe.
        - Apply the same size + ratio thresholds.

    Download decision (remote file cannot be sampled cheaply):
      Use remote path extension as a proxy for compressibility.  For download
      the exec-channel stdout is always the bottleneck (~3.5 MB/s), so any
      compression ratio ≥ 2x translates directly to faster transfers.
      Unknown extensions default to non-streaming (conservative).
    """
    if upload:
        if os.path.isdir(local_path):
            total_size, ratio = _dir_stats(local_path)
            if total_size < _SIZE_SMALL:
                return False
            return ratio >= _UPLOAD_RATIO_MIN

        # Single file path.
        ext = os.path.splitext(local_path)[1].lower()
        size = os.path.getsize(local_path)
        if size < _SIZE_SMALL:
            return False
        if ext in _INCOMPRESSIBLE_EXTS:
            return False
        # Fast entropy check: skip expensive gzip probe for obviously incompressible data.
        entropy = _sample_entropy(local_path)
        if entropy > _ENTROPY_INCOMPRESSIBLE:
            return False
        # Measure actual compression ratio on a 64 KB sample (~0.5 ms overhead).
        ratio = _sample_compression_ratio(local_path)
        return ratio >= _UPLOAD_RATIO_MIN

    # Download: extension heuristic (cannot sample remote file cheaply).
    ext = os.path.splitext(remote_path)[1].lower()
    if ext in _INCOMPRESSIBLE_EXTS:
        return False
    if ext in _COMPRESSIBLE_EXTS:
        return True
    # No extension (likely a directory) or unknown extension → streaming is
    # the safer default for download: exec-channel stdout is the bottleneck
    # and any compressible content benefits; worst case is a small penalty for
    # truly incompressible directories.
    if not ext:
        return True
    return False


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
    has_tls_options = any((cert_file, key_file, ca_file))
    if not has_tls_options and verify_server:
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
        should_exit.set()


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
        should_exit.set()
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
    except (OSError, RuntimeError, ValueError):
        return

    last_size = None
    try:
        while not should_exit.is_set():
            try:
                await asyncio.wait_for(resize_event.wait(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            resize_event.clear()
            terminal_size = shutil.get_terminal_size()
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
        except (OSError, RuntimeError, ValueError):
            should_exit.set()


async def send_terminal_resize(ws, rows=None, cols=None):
    """发送终端尺寸到 WebSocket（协议: RESIZE:cols:rows）"""
    if rows is None or cols is None:
        terminal_size = shutil.get_terminal_size()
        if rows is None:
            rows = terminal_size.lines
        if cols is None:
            cols = terminal_size.columns

    has_valid_size = rows is not None and cols is not None and rows > 0 and cols > 0
    if has_valid_size:
        try:
            await ws.send(f"RESIZE:{cols}:{rows}")
        except websockets.ConnectionClosed:
            return


def build_exec_uri(connection: ExecConnection, invocation: ExecInvocation):
    """Build exec websocket URI.

    ``command`` may be a **string** (legacy, single-element argv) or a **list**
    of strings (recommended).  When a list is given, each element is passed as
    a separate ``command=`` query parameter so the gateway constructs a proper
    ``[]string`` argv instead of a single-element array containing the entire
    shell command.
    """
    query_params = []
    if invocation.instance:
        query_params.append(f"instance={quote(invocation.instance)}")
    if invocation.command:
        if isinstance(invocation.command, list):
            for arg in invocation.command:
                query_params.append(f"command={quote(arg)}")
        else:
            query_params.append(f"command={quote(invocation.command)}")
    if invocation.allocate_tty is not None:
        query_params.append(f"tty={str(invocation.allocate_tty).lower()}")
    if invocation.rows:
        query_params.append(f"rows={invocation.rows}")
    if invocation.cols:
        query_params.append(f"cols={invocation.cols}")
    if connection.user:
        query_params.append(f"tenant_id={quote(connection.user)}")
    if connection.token:
        query_params.append(f"token={quote(connection.token)}")

    query_string = "&".join(query_params)
    protocol = "wss" if connection.use_ssl else "ws"
    uri = f"{protocol}://{connection.host}:{connection.port}/terminal/ws"
    if query_string:
        uri += f"?{query_string}"
    return uri


def build_exec_ssl_context(connection: ExecConnection):
    """Build SSL context for exec websocket when TLS is enabled."""
    if not connection.use_ssl:
        return None
    return create_ssl_context(
        cert_file=connection.cert_file,
        key_file=connection.key_file,
        ca_file=connection.ca_file,
        verify_server=connection.verify_server,
        quiet=connection.quiet,
    )


async def _drain_websocket(ws, should_exit, quiet=False, writer=None, process_exited=None):
    """Read websocket messages until the process exits or the socket closes.

    ``process_exited`` is an :class:`asyncio.Event` that is set **only** when the
    remote process confirmed its exit via the ``[Process exited]`` text frame.
    Callers that need a strong guarantee (e.g. upload) can check this event after
    ``should_exit`` fires: if it is not set the WebSocket was closed before the
    process-exit notification arrived, meaning the operation may be incomplete.
    """
    try:
        async for message in ws:
            if should_exit.is_set():
                break
            if isinstance(message, str):
                if quiet and message.strip() == "[Process exited]":
                    if process_exited is not None:
                        process_exited.set()
                    should_exit.set()
                    break
                if writer is not None:
                    writer.write(message.encode("utf-8"))
                continue

            if writer is not None:
                writer.write(message)
    except websockets.exceptions.ConnectionClosed:
        # Server closed the connection after the process completed.
        # This can race with the [Process exited] text frame — if the close
        # frame arrives before we process the text frame, we still know the
        # process exited because all data was already sent and the remote
        # command has finished.
        if process_exited is not None:
            process_exited.set()
    except Exception:
        if process_exited is not None:
            process_exited.set()
    finally:
        should_exit.set()


def _connect_copy_websocket(uri, ssl_context):
    """Open a copy websocket without the websockets library keepalive.

    File copy streams can be quiet for longer than the library's default
    ping_timeout on slow or jittery links. The copy protocol already finishes
    by draining stdout until "[Process exited]" / EOF, so library-level pings
    must not tear down a long-running transfer.
    """
    return websockets.connect(
        uri,
        ssl=ssl_context,
        ping_interval=None,
        ping_timeout=None,
    )


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


async def copy_to_remote(connection: ExecConnection, request: CopyRequest):
    """Upload a local file into an instance via the exec websocket.

    Requires the target instance container to have ``sh``, ``tar``,
    ``mkdir``, and ``head`` available (standard in most Linux base images).
    """
    source = Path(request.local_path)
    archive_path = _create_tar_archive(source, Path(request.remote_path).name)
    archive_size = Path(archive_path).stat().st_size
    command = [
        "sh", "-c",
        "mkdir -p \"$(dirname \"$1\")\" && head -c \"$2\" | tar -xmf - -C \"$(dirname \"$1\")\"",
        "sh", request.remote_path, str(archive_size),
    ]
    uri = build_exec_uri(
        connection,
        ExecInvocation(instance=request.instance, command=command, allocate_tty=False),
    )
    ssl_context = build_exec_ssl_context(_quiet_connection(connection))

    try:
        async with _connect_copy_websocket(uri, ssl_context) as ws:
            should_exit = asyncio.Event()
            process_exited = asyncio.Event()
            tasks = [
                asyncio.create_task(_drain_websocket(ws, should_exit, quiet=True, process_exited=process_exited)),
            ]
            try:
                with open(archive_path, "rb") as file_obj:
                    while True:
                        chunk = file_obj.read(64 * 1024)
                        if not chunk:
                            break
                        await ws.send(chunk)
                await should_exit.wait()
                if not process_exited.is_set():
                    raise RuntimeError(
                        "WebSocket closed before process-exit confirmation — "
                        "upload may be incomplete"
                    )
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


async def copy_from_remote(connection: ExecConnection, request: CopyRequest):
    """Download a file from an instance via the exec websocket."""
    command = [
        "sh", "-c",
        "tar -cf - -C \"$(dirname \"$1\")\" \"$(basename \"$1\")\"",
        "sh", request.remote_path,
    ]
    uri = build_exec_uri(
        connection,
        ExecInvocation(instance=request.instance, command=command, allocate_tty=False),
    )
    ssl_context = build_exec_ssl_context(_quiet_connection(connection))

    archive_file = tempfile.NamedTemporaryFile(suffix=".tar", delete=False)
    archive_file.close()
    try:
        async with _connect_copy_websocket(uri, ssl_context) as ws:
            should_exit = asyncio.Event()
            with open(archive_file.name, "wb") as file_obj:
                tasks = [
                    asyncio.create_task(_drain_websocket(ws, should_exit, quiet=True, writer=file_obj)),
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

        _restore_from_tar(archive_file.name, request.local_path)
    finally:
        Path(archive_file.name).unlink(missing_ok=True)


async def copy_to_remote_streaming(connection: ExecConnection, request: CopyRequest):
    """Upload a local file into an instance using full-pipeline streaming (no temp file).

    Generates tar.gz chunks on-the-fly via a background thread + OS pipe and sends
    each chunk as a binary WebSocket frame immediately.  After all data is sent,
    a ``"STDIN_EOF"`` text frame signals the remote side to close the tar stdin so
    the tar process exits naturally — no pre-buffering or temp file required.

    Requires the target instance container to have ``sh``, ``tar``, and ``mkdir``
    available (standard in most Linux base images).
    """
    source = Path(request.local_path)

    command = [
        "sh", "-c",
        "mkdir -p \"$(dirname \"$1\")\" && tar -xzmf - -C \"$(dirname \"$1\")\"",
        "sh", request.remote_path,
    ]
    uri = build_exec_uri(
        connection,
        ExecInvocation(instance=request.instance, command=command, allocate_tty=False),
    )
    ssl_context = build_exec_ssl_context(_quiet_connection(connection))

    # OS pipe: tar writer thread → read end → WebSocket chunks
    r_fd, w_fd = os.pipe()
    write_error: list = []
    # Hoisted outside async with so they are accessible after the block for
    # write_error suppression logic.
    server_closed_early = False

    def _tar_writer():
        try:
            with os.fdopen(w_fd, "wb", buffering=0) as wf:
                with tarfile.open(fileobj=wf, mode="w|gz") as archive:
                    archive.add(str(source), arcname=Path(request.remote_path).name)
        except Exception as exc:  # noqa: BLE001
            write_error.append(exc)

    writer = threading.Thread(target=_tar_writer, daemon=True)
    writer.start()

    loop = asyncio.get_event_loop()
    chunk_size = 64 * 1024

    async with _connect_copy_websocket(uri, ssl_context) as ws:
        should_exit = asyncio.Event()
        process_exited = asyncio.Event()
        tasks = [
            asyncio.create_task(_drain_websocket(ws, should_exit, quiet=True, process_exited=process_exited)),
        ]
        try:
            server_closed_early = False
            with os.fdopen(r_fd, "rb", buffering=0) as rf:
                while True:
                    chunk = await loop.run_in_executor(None, rf.read, chunk_size)
                    if not chunk:
                        break
                    try:
                        await ws.send(chunk)
                    except websockets.exceptions.ConnectionClosed:
                        # The remote tar process may have exited after consuming a complete
                        # gzip end-of-stream marker before Python finished sending all chunks.
                        # Stop sending; wait for _drain_websocket to confirm the exit.
                        server_closed_early = True
                        break
            if not server_closed_early:
                # All tar data sent — signal remote tar stdin EOF
                try:
                    await ws.send("STDIN_EOF")
                except websockets.exceptions.ConnectionClosed:
                    server_closed_early = True
            await should_exit.wait()
            if not process_exited.is_set():
                raise RuntimeError(
                    "WebSocket closed before process-exit confirmation — "
                    "upload may be incomplete"
                )
        finally:
            for task in tasks:
                if task.done():
                    continue
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    writer.join(timeout=30)
    if write_error:
        # When server_closed_early (tar consumed the complete gzip stream and exited
        # naturally before Python drained the pipe), closing r_fd causes _tar_writer
        # to get a BrokenPipeError on the next write.  This is expected: the upload
        # was already confirmed successful (process_exited was set; otherwise
        # RuntimeError would have been raised above).  Suppress the spurious error.
        if server_closed_early and isinstance(write_error[0], BrokenPipeError):
            pass
        else:
            raise write_error[0]


async def copy_from_remote_streaming(connection: ExecConnection, request: CopyRequest):
    """Download a file from an instance using full-pipeline streaming (no temp file).

    The remote command produces a gzip-compressed tar stream on stdout, which is
    piped through the WebSocket directly into tarfile extraction on the client side.
    """
    command = [
        "sh", "-c",
        "tar -czf - -C \"$(dirname \"$1\")\" \"$(basename \"$1\")\"",
        "sh", request.remote_path,
    ]
    uri = build_exec_uri(
        connection,
        ExecInvocation(instance=request.instance, command=command, allocate_tty=False),
    )
    ssl_context = build_exec_ssl_context(_quiet_connection(connection))

    target = Path(request.local_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    r_fd, w_fd = os.pipe()
    extract_error: list = []

    def _tar_reader():
        try:
            with os.fdopen(r_fd, "rb", buffering=0) as r_file:
                with tempfile.TemporaryDirectory() as unpack_dir:
                    unpack_root = Path(unpack_dir)
                    with tarfile.open(fileobj=r_file, mode="r|gz") as archive:
                        archive.extractall(unpack_root)

                    entries = list(unpack_root.iterdir())
                    if len(entries) != 1:
                        extract_error.append(RuntimeError("unexpected archive layout"))
                        return
                    source_root = entries[0]

                    if source_root.is_dir():
                        if target.exists() and target.is_dir():
                            shutil.copytree(source_root, target, dirs_exist_ok=True)
                        else:
                            shutil.move(str(source_root), str(target))
                    else:
                        if target.exists() and target.is_dir():
                            extract_error.append(
                                RuntimeError(f"cannot overwrite directory target with file: {target}")
                            )
                            return
                        if target.exists():
                            target.unlink()
                        shutil.move(str(source_root), str(target))
        except Exception as exc:
            extract_error.append(exc)

    extract_thread = threading.Thread(target=_tar_reader, daemon=True)
    extract_thread.start()

    try:
        async with _connect_copy_websocket(uri, ssl_context) as ws:
            should_exit = asyncio.Event()
            w_file = os.fdopen(w_fd, "wb", buffering=0)
            w_fd = -1  # ownership transferred

            async def _recv_and_pipe():
                try:
                    async for message in ws:
                        if should_exit.is_set():
                            break
                        if isinstance(message, bytes):
                            w_file.write(message)
                        elif isinstance(message, str) and message.strip() == "[Process exited]":
                            should_exit.set()
                            break
                except Exception:
                    should_exit.set()
                finally:
                    w_file.close()
                    should_exit.set()

            tasks = [
                asyncio.create_task(_recv_and_pipe()),
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
    finally:
        if w_fd != -1:
            os.close(w_fd)

    extract_thread.join(timeout=30)
    if extract_error:
        raise extract_error[0]


async def run_client(connection: ExecConnection, invocation: ExecInvocation):
    tty_enabled = bool(invocation.allocate_tty)

    # 获取当前终端的实际尺寸作为默认值
    if invocation.rows is None or invocation.cols is None:
        try:
            terminal_size = shutil.get_terminal_size()
            if invocation.rows is None:
                invocation.rows = terminal_size.lines
            if invocation.cols is None:
                invocation.cols = terminal_size.columns
        except Exception:
            # 如果无法获取，使用服务端默认值
            pass

    uri = build_exec_uri(connection, invocation)

    if tty_enabled:
        if invocation.instance:
            print(f"Connecting to {invocation.instance}...\nPress Ctrl+] to disconnect", file=sys.stderr)
        else:
            print("Connecting...\nPress Ctrl+] to disconnect", file=sys.stderr)
    
    # Create SSL context if needed
    ssl_context = build_exec_ssl_context(connection)
    if connection.use_ssl:
        if ssl_context and tty_enabled:
            print("Using mutual TLS authentication", file=sys.stderr)
        elif not ssl_context and tty_enabled:
            print("Warning: SSL requested but failed to create SSL context", file=sys.stderr)

    try:
        async with websockets.connect(uri, ssl=ssl_context) as ws:
            should_exit = asyncio.Event()

            interactive = tty_enabled and sys.stdin.isatty()

            if tty_enabled:
                await send_terminal_resize(ws, rows=invocation.rows, cols=invocation.cols)

            if interactive:
                raw_term = RawTerminal(sys.stdin.fileno())
                raw_term.__enter__()

            try:
                # 同时处理输入和输出
                tasks = [
                    asyncio.create_task(read_websocket(ws, should_exit, quiet=connection.quiet)),
                    asyncio.create_task(heartbeat_loop(ws, should_exit, quiet=connection.quiet)),
                ]
                if invocation.stdin or interactive:
                    tasks.append(asyncio.create_task(read_stdin(ws, should_exit, quiet=connection.quiet)))
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
        if not connection.quiet:
            print("\n[Interrupted]", file=sys.stderr)
    except Exception as e:
        if not connection.quiet:
            print(f"\nConnection error: {e}", file=sys.stderr)
