#!/usr/bin/env python3
import importlib.util
import io
from pathlib import Path
import sys
import types
from contextlib import redirect_stdout
from unittest import mock
import unittest


class TestYrCluster(unittest.TestCase):
    def load_yrcluster_with_stubbed_deps(self):
        cluster_path = Path(__file__).resolve().parents[1] / "cli" / "cluster.py"
        spec = importlib.util.spec_from_file_location("yr_cluster_for_test", cluster_path)
        cluster = importlib.util.module_from_spec(spec)

        fake_click = types.ModuleType("click")
        fake_click.option = lambda *args, **kwargs: lambda func: func
        fake_click.argument = lambda *args, **kwargs: lambda func: func
        fake_click.version_option = lambda *args, **kwargs: lambda func: func
        fake_click.echo = print
        fake_click.ClickException = RuntimeError

        def group_decorator(*args, **kwargs):
            def decorate(func):
                func.command = lambda *a, **kw: lambda command_func: command_func
                return func

            return decorate

        fake_click.group = group_decorator

        with mock.patch.dict(sys.modules, {"click": fake_click}):
            spec.loader.exec_module(cluster)
        return cluster

    def test_token_require_calls_iam_directly_from_cluster(self):
        cluster = self.load_yrcluster_with_stubbed_deps()

        result = types.SimpleNamespace(stdout="HTTP/1.1 200 OK\r\nX-Auth: tenant-token\r\n\r\n")

        with (
            mock.patch.object(cluster.subprocess, "run", return_value=result) as run,
            redirect_stdout(io.StringIO()) as output,
        ):
            cluster.token_require("tenant-a", 3600, "developer", "127.0.0.1:31112")

        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["curl", "-sS", "--fail", "-D"])
        self.assertIn("-X", command)
        self.assertIn("GET", command)
        self.assertIn("-H", command)
        self.assertIn("X-Tenant-ID: tenant-a", command)
        self.assertIn("X-Role: developer", command)
        self.assertIn("X-TTL: 3600", command)
        self.assertEqual(command[-1], "http://127.0.0.1:31112/iam-server/v1/token/require")
        self.assertIn("Token: tenant-token", output.getvalue())

    def test_token_abandon_calls_iam_directly_from_cluster(self):
        cluster = self.load_yrcluster_with_stubbed_deps()

        result = types.SimpleNamespace(stdout="")

        with mock.patch.object(cluster.subprocess, "run", return_value=result) as run, redirect_stdout(io.StringIO()):
            cluster.token_abandon("tenant-token", "tenant-a", "127.0.0.1:31112")

        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["curl", "-sS", "--fail", "-D"])
        self.assertIn("-X", command)
        self.assertIn("POST", command)
        self.assertIn("-H", command)
        self.assertIn("X-Auth: tenant-token", command)
        self.assertIn("X-Tenant-ID: tenant-a", command)
        self.assertEqual(command[-1], "http://127.0.0.1:31112/iam-server/v1/token/abandon")


if __name__ == "__main__":
    unittest.main()
