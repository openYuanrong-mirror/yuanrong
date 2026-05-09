#!/usr/bin/env python3
"""Tests for yrcli cp over the exec websocket channel."""
import asyncio
import io
import socket
import tempfile
import tarfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from unittest.mock import patch

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
                        "127.0.0.1",
                        str(port),
                        instance="instance-a",
                        local_path=local_path,
                        remote_path="/tmp/remote.bin",
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
                        "127.0.0.1",
                        str(port),
                        instance="instance-dir",
                        local_path=str(source_dir),
                        remote_path="/tmp/remote-dir",
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
                        "127.0.0.1",
                        str(port),
                        instance="instance-b",
                        remote_path="/var/remote.bin",
                        local_path=local_path,
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
                        "127.0.0.1",
                        str(port),
                        instance="instance-dir",
                        remote_path="/var/remote-dir",
                        local_path=str(local_dir),
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

        async def fake_copy_to_remote(host, port, **kwargs):
            calls.append((host, port, kwargs))

        with runner.isolated_filesystem():
            Path("local.txt").write_bytes(b"upload")
            with patch.object(scripts, "copy_to_remote", new=fake_copy_to_remote):
                result = runner.invoke(
                    scripts.cli,
                    ["--server-address", "127.0.0.1:30123", "cp", "local.txt", "inst-9:/tmp/remote.txt"],
                )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(len(calls), 1)
        host, port, kwargs = calls[0]
        self.assertEqual(host, "127.0.0.1")
        self.assertEqual(port, "30123")
        self.assertEqual(kwargs["instance"], "inst-9")
        self.assertEqual(kwargs["remote_path"], "/tmp/remote.txt")
        self.assertTrue(kwargs["local_path"].endswith("local.txt"))

    def test_cp_command_rejects_invalid_operands(self):
        runner = CliRunner()
        result = runner.invoke(
            scripts.cli,
            ["--server-address", "127.0.0.1:30123", "cp", "left.txt", "right.txt"],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("exactly one side must be remote", result.output.lower())


if __name__ == "__main__":
    unittest.main()
