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
import shutil
import ssl
import sys
import termios
import tty
import websockets


def create_ssl_context(
    cert_file=None,
    key_file=None,
    ca_file=None,
    verify_server=True
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
    # If no certificates are provided, return None (no TLS)
    if not cert_file and not key_file and not ca_file:
        return None
    
    try:
        # Create SSL context
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        
        # Load client certificate and key for mutual authentication
        if cert_file and key_file:
            if not os.path.exists(cert_file):
                print(f"Warning: Client certificate file not found: {cert_file}", file=sys.stderr)
            elif not os.path.exists(key_file):
                print(f"Warning: Client key file not found: {key_file}", file=sys.stderr)
            else:
                ssl_context.load_cert_chain(cert_file, key_file)
        
        # Load CA certificate for server verification
        if ca_file:
            if not os.path.exists(ca_file):
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
            print("Warning: Server certificate verification is disabled (insecure)", file=sys.stderr)
        
        return ssl_context
    except Exception as e:
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


async def read_stdin(ws, should_exit):
    """读取标准输入并发送到 WebSocket"""
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader(loop=loop)
    protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    try:
        while not should_exit.is_set():
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=0.1)
                if not data:
                    break
                # 检测 Ctrl+] (ASCII 29) 作为退出信号
                if b"\x1d" in data:
                    print(
                        "\n[Escape sequence detected, disconnecting...]",
                        file=sys.stderr,
                    )
                    should_exit.set()
                    break
                await ws.send(data)
            except asyncio.TimeoutError:
                continue
    except Exception:
        pass
    finally:
        should_exit.set()


async def read_websocket(ws, should_exit):
    """从 WebSocket 读取输出并写入标准输出"""
    try:
        async for message in ws:
            if should_exit.is_set():
                break
            if isinstance(message, bytes):
                os.write(sys.stdout.fileno(), message)
            else:
                os.write(sys.stdout.fileno(), message.encode("utf-8"))
    except Exception:
        pass
    finally:
        should_exit.set()


async def run_client(
    host, port, instance=None, command=None, tty=None, stdin=None, rows=None, cols=None, user=None,
    use_ssl=False, cert_file=None, key_file=None, ca_file=None, verify_server=True
):
    # 获取当前终端的实际尺寸作为默认值
    if rows is None or cols is None:
        try:
            terminal_size = shutil.get_terminal_size()
            if rows is None:
                rows = terminal_size.lines
            if cols is None:
                cols = terminal_size.columns
            print(f"Detected terminal size: {cols}x{rows}", file=sys.stderr)
        except Exception:
            # 如果无法获取，使用服务端默认值
            pass

    # 构建 URL query 参数
    query_params = []
    if instance:
        query_params.append(f"instance={instance}")
    if command:
        from urllib.parse import quote

        query_params.append(f"command={quote(command)}")
    if tty is not None:
        query_params.append(f"tty={str(tty).lower()}")
    if rows:
        query_params.append(f"rows={rows}")
    if cols:
        query_params.append(f"cols={cols}")
    if user:
        query_params.append(f"tenant_id={quote(user)}")

    query_string = "&".join(query_params)
    
    # Determine protocol based on SSL usage
    protocol = "wss" if use_ssl else "ws"
    uri = f"{protocol}://{host}:{port}/terminal/ws"
    if query_string:
        uri += f"?{query_string}"

    print(f"Connecting to {uri}...", file=sys.stderr)
    print("Press Ctrl+] to disconnect", file=sys.stderr)
    
    # Create SSL context if needed
    ssl_context = None
    if use_ssl:
        ssl_context = create_ssl_context(
            cert_file=cert_file,
            key_file=key_file,
            ca_file=ca_file,
            verify_server=verify_server
        )
        if ssl_context:
            print("Using mutual TLS authentication", file=sys.stderr)
        else:
            print("Warning: SSL requested but failed to create SSL context", file=sys.stderr)

    try:
        async with websockets.connect(uri, ssl=ssl_context) as ws:
            should_exit = asyncio.Event()

            with RawTerminal(sys.stdin.fileno()):
                # 同时处理输入和输出
                done, pending = await asyncio.wait(
                    [
                        asyncio.create_task(read_stdin(ws, should_exit)),
                        asyncio.create_task(read_websocket(ws, should_exit)),
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # 取消未完成的任务
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
    except KeyboardInterrupt:
        print("\n[Interrupted]", file=sys.stderr)
    except Exception as e:
        print(f"\nConnection error: {e}", file=sys.stderr)
