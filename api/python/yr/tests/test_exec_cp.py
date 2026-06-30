#!/usr/bin/env python3
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
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

"""Tests for yrcli cp over the exec websocket channel."""
import asyncio
import io
import json
import socket
import tempfile
import tarfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr
from urllib.parse import parse_qs, unquote, urlparse
from unittest.mock import AsyncMock, patch

import websockets
from click.testing import CliRunner

from yr.cli import exec as exec_cli
from yr.cli import scripts


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _request_path(websocket):
    request = getattr(websocket, "request", None)
    if request is not None:
        return request.path
    return websocket.path


class TestCopyPathParsing(unittest.TestCase):

    def test_parse_upload_targets(self):
        parsed = scripts.parse_cp_targets("local.txt", "inst-1:/tmp/remote.txt")
        self.assertTrue(parsed["upload"])
        self.assertEqual(parsed["instance"], "inst-1")
        self.assertEqual(parsed["local_path"], "local.txt")
        self.assertEqual(parsed["remote_path"], "/tmp/remote.txt")

    def test_parse_download_targets(self):
        parsed = scripts.parse_cp_targets("inst-2:/var/data.bin", "local.bin")
        self.assertFalse(parsed["upload"])
        self.assertEqual(parsed["instance"], "inst-2")
        self.assertEqual(parsed["local_path"], "local.bin")
        self.assertEqual(parsed["remote_path"], "/var/data.bin")

    def test_parse_requires_exactly_one_remote_side(self):
        with self.assertRaises(ValueError):
            scripts.parse_cp_targets("left.txt", "right.txt")
        with self.assertRaises(ValueError):
            scripts.parse_cp_targets("inst-1:/a", "inst-2:/b")


class TestCopyTransport(unittest.TestCase):

    def test_copy_websocket_disables_library_keepalive(self):
        calls = []
        sentinel = object()

        def fake_connect(*args, **kwargs):
            calls.append((args, kwargs))
            return sentinel

        with patch.object(exec_cli.websockets, "connect", new=fake_connect):
            result = exec_cli._connect_copy_websocket("ws://example/ws", ssl_context=None)

        self.assertIs(result, sentinel)
        self.assertEqual(calls[0][0], ("ws://example/ws",))
        self.assertIsNone(calls[0][1]["ssl"])
        self.assertIsNone(calls[0][1]["ping_interval"])
        self.assertIsNone(calls[0][1]["ping_timeout"])

    def test_copy_to_remote_streams_file_tar(self):
        payload = b"\x00copy-to-remote\npayload\xff"
        port = _find_free_port()
        received = {}

        async def _run():
            async def handler(websocket):
                received["path"] = _request_path(websocket)
                archive = bytearray()
                while True:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=0.2)
                    except asyncio.TimeoutError:
                        break
                    if isinstance(message, bytes):
                        archive.extend(message)
                received["archive"] = bytes(archive)
                await websocket.send("\r\n[Process exited]\r\n")
                await websocket.close()

            async with await websockets.serve(
                handler,
                "127.0.0.1",
                port,
                ping_interval=None,
                ping_timeout=None,
            ):
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(payload)
                    local_path = tmp.name
                try:
                    await exec_cli.copy_to_remote(
                        exec_cli.ExecConnection("127.0.0.1", str(port)),
                        exec_cli.CopyRequest("instance-a", local_path, "/tmp/remote.bin"),
                    )
                finally:
                    Path(local_path).unlink(missing_ok=True)

        asyncio.run(_run())

        query = parse_qs(urlparse(received["path"]).query)
        self.assertEqual(query["instance"], ["instance-a"])
        self.assertEqual(query["tty"], ["false"])
        command = unquote(query["command"][0])
        self.assertIn("head -c", command)
        self.assertIn("tar -xmf -", command)
        self.assertIn("/tmp/remote.bin", command)
        with tarfile.open(fileobj=io.BytesIO(received["archive"]), mode="r:") as archive:
            member = archive.getmember("remote.bin")
            self.assertEqual(archive.extractfile(member).read(), payload)

    def test_copy_directory_to_remote_streams_directory_tar(self):
        port = _find_free_port()
        received = {}

        async def _run():
            async def handler(websocket):
                received["path"] = _request_path(websocket)
                archive = bytearray()
                while True:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=0.2)
                    except asyncio.TimeoutError:
                        break
                    if isinstance(message, bytes):
                        archive.extend(message)
                received["archive"] = bytes(archive)
                await websocket.send("\r\n[Process exited]\r\n")
                await websocket.close()

            async with await websockets.serve(
                handler,
                "127.0.0.1",
                port,
                ping_interval=None,
                ping_timeout=None,
            ):
                with tempfile.TemporaryDirectory() as tmpdir:
                    source_dir = Path(tmpdir) / "source"
                    source_dir.mkdir()
                    (source_dir / "nested").mkdir()
                    (source_dir / "root.txt").write_text("root-data")
                    (source_dir / "nested" / "child.txt").write_text("child-data")
                    await exec_cli.copy_to_remote(
                        exec_cli.ExecConnection("127.0.0.1", str(port)),
                        exec_cli.CopyRequest("instance-dir", str(source_dir), "/tmp/remote-dir"),
                    )

        asyncio.run(_run())

        query = parse_qs(urlparse(received["path"]).query)
        self.assertEqual(query["instance"], ["instance-dir"])
        command = unquote(query["command"][0])
        self.assertIn("head -c", command)
        self.assertIn("tar -xmf -", command)
        self.assertIn("/tmp/remote-dir", command)
        with tarfile.open(fileobj=io.BytesIO(received["archive"]), mode="r:") as archive:
            names = archive.getnames()
            self.assertIn("remote-dir/root.txt", names)
            self.assertIn("remote-dir/nested/child.txt", names)

    def test_copy_from_remote_writes_local_file(self):
        payload = b"download-payload-\x00-\xff"
        port = _find_free_port()
        received = {}

        async def _run():
            async def handler(websocket):
                received["path"] = _request_path(websocket)
                archive_buf = io.BytesIO()
                with tarfile.open(fileobj=archive_buf, mode="w:") as archive:
                    info = tarfile.TarInfo("remote.bin")
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
                raw = archive_buf.getvalue()
                await websocket.send(raw[:8])
                await websocket.send(raw[8:])
                await websocket.send("\r\n[Process exited]\r\n")
                await websocket.close()

            async with await websockets.serve(
                handler,
                "127.0.0.1",
                port,
                ping_interval=None,
                ping_timeout=None,
            ):
                with tempfile.TemporaryDirectory() as tmpdir:
                    local_path = str(Path(tmpdir) / "download.bin")
                    await exec_cli.copy_from_remote(
                        exec_cli.ExecConnection("127.0.0.1", str(port)),
                        exec_cli.CopyRequest("instance-b", local_path, "/var/remote.bin"),
                    )
                    received["file_bytes"] = Path(local_path).read_bytes()

        asyncio.run(_run())

        self.assertEqual(received["file_bytes"], payload)
        query = parse_qs(urlparse(received["path"]).query)
        self.assertEqual(query["instance"], ["instance-b"])
        self.assertEqual(query["tty"], ["false"])
        command = unquote(query["command"][0])
        self.assertIn("tar -cf -", command)
        self.assertIn("/var/remote.bin", command)

    def test_copy_directory_from_remote_extracts_locally(self):
        port = _find_free_port()
        received = {}

        async def _run():
            async def handler(websocket):
                received["path"] = _request_path(websocket)
                archive_buf = io.BytesIO()
                with tarfile.open(fileobj=archive_buf, mode="w:") as archive:
                    for name, data in (
                        ("remote-dir/root.txt", b"root-data"),
                        ("remote-dir/nested/child.txt", b"child-data"),
                    ):
                        info = tarfile.TarInfo(name)
                        info.size = len(data)
                        archive.addfile(info, io.BytesIO(data))
                raw = archive_buf.getvalue()
                await websocket.send(raw[:16])
                await websocket.send(raw[16:])
                await websocket.send("\r\n[Process exited]\r\n")
                await websocket.close()

            async with await websockets.serve(
                handler,
                "127.0.0.1",
                port,
                ping_interval=None,
                ping_timeout=None,
            ):
                with tempfile.TemporaryDirectory() as tmpdir:
                    local_dir = Path(tmpdir) / "local-dir"
                    await exec_cli.copy_from_remote(
                        exec_cli.ExecConnection("127.0.0.1", str(port)),
                        exec_cli.CopyRequest("instance-dir", str(local_dir), "/var/remote-dir"),
                    )
                    received["root"] = (local_dir / "root.txt").read_text()
                    received["child"] = (local_dir / "nested" / "child.txt").read_text()

        asyncio.run(_run())

        self.assertEqual(received["root"], "root-data")
        self.assertEqual(received["child"], "child-data")
        query = parse_qs(urlparse(received["path"]).query)
        self.assertEqual(query["instance"], ["instance-dir"])
        command = unquote(query["command"][0])
        self.assertIn("tar -cf -", command)
        self.assertIn("/var/remote-dir", command)


class TestCopyCLI(unittest.TestCase):

    def test_cp_command_dispatches_upload(self):
        runner = CliRunner()
        calls = []

        async def fake_copy_to_remote(connection, request):
            calls.append((connection, request))

        with runner.isolated_filesystem():
            Path("local.txt").write_bytes(b"upload")
            with patch.object(scripts, "copy_to_remote", new=fake_copy_to_remote):
                result = runner.invoke(
                    scripts.cli,
                    ["--server-address", "127.0.0.1:30123", "cp", "local.txt", "inst-9:/tmp/remote.txt"],
                )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(len(calls), 1)
        connection, request = calls[0]
        self.assertEqual(connection.host, "127.0.0.1")
        self.assertEqual(connection.port, "30123")
        self.assertEqual(request.instance, "inst-9")
        self.assertEqual(request.remote_path, "/tmp/remote.txt")
        self.assertTrue(request.local_path.endswith("local.txt"))

    def test_cp_command_rejects_invalid_operands(self):
        runner = CliRunner()
        result = runner.invoke(
            scripts.cli,
            ["--server-address", "127.0.0.1:30123", "cp", "left.txt", "right.txt"],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("exactly one side must be remote", result.output.lower())


class TestDeployCLI(unittest.TestCase):

    def test_deploy_packages_with_selected_user(self):
        runner = CliRunner()
        package_calls = []

        def fake_package(backend, code_path, package_format, user=None):
            package_calls.append((backend, code_path, package_format, user))
            return code_path, "ds://code-test.zip"

        function_info = {"name": "0@faaspy@hello", "versionNumber": "latest"}

        with runner.isolated_filesystem():
            Path("function.json").write_text(
                json.dumps({"name": "0@faaspy@hello", "kind": "faas"}),
                encoding="utf-8",
            )
            with patch.object(scripts, "package", new=fake_package), \
                    patch.object(scripts, "query_function", return_value=(False, {})), \
                    patch.object(scripts, "deploy_function", return_value=(True, function_info)):
                result = runner.invoke(
                    scripts.cli,
                    [
                        "--server-address",
                        "127.0.0.1:38888",
                        "--ds-address",
                        "127.0.0.1:38888",
                        "--user",
                        "tenant-0",
                        "deploy",
                        "--code-path",
                        ".",
                        "--function-json",
                        "function.json",
                    ],
                )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(package_calls, [("ds", ".", "zip", "tenant-0")])


class TestExecQuietMode(unittest.TestCase):

    class _FakeWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class _TtyLikeStdin:
        @staticmethod
        def isatty():
            return True

        @staticmethod
        def fileno():
            return 0

    def test_run_client_non_tty_does_not_use_local_terminal(self):
        stderr = io.StringIO()
        send_resize = AsyncMock()

        with patch.object(exec_cli.websockets, "connect", return_value=self._FakeWebSocket()), \
                patch.object(exec_cli, "send_terminal_resize", send_resize), \
                redirect_stderr(stderr):
            asyncio.run(
                exec_cli.run_client(
                    exec_cli.ExecConnection("127.0.0.1", "30123", quiet=False),
                    exec_cli.ExecInvocation(instance="inst-1", command="pwd", allocate_tty=False),
                )
            )

        self.assertEqual(stderr.getvalue(), "")
        send_resize.assert_not_awaited()

    def test_run_client_non_tty_ignores_local_tty_stdin(self):
        stderr = io.StringIO()
        send_resize = AsyncMock()
        read_stdin = AsyncMock()

        with patch.object(exec_cli.websockets, "connect", return_value=self._FakeWebSocket()), \
                patch.object(exec_cli, "send_terminal_resize", send_resize), \
                patch.object(exec_cli, "read_stdin", read_stdin), \
                patch.object(exec_cli, "RawTerminal") as raw_terminal, \
                patch.object(exec_cli.sys, "stdin", self._TtyLikeStdin()), \
                redirect_stderr(stderr):
            asyncio.run(
                exec_cli.run_client(
                    exec_cli.ExecConnection("127.0.0.1", "30123", quiet=False),
                    exec_cli.ExecInvocation(instance="inst-1", command="pwd", allocate_tty=False),
                )
            )

        self.assertEqual(stderr.getvalue(), "")
        send_resize.assert_not_awaited()
        read_stdin.assert_not_awaited()
        raw_terminal.assert_not_called()

    def test_run_client_quiet_suppresses_local_connection_error(self):
        stderr = io.StringIO()

        with patch.object(exec_cli.websockets, "connect", side_effect=RuntimeError("boom")), \
                redirect_stderr(stderr):
            asyncio.run(
                exec_cli.run_client(
                    exec_cli.ExecConnection("127.0.0.1", "30123", quiet=True),
                    exec_cli.ExecInvocation(instance="inst-1", command="pwd", allocate_tty=False),
                )
            )

        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
