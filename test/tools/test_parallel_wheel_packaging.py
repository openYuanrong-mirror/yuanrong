#!/usr/bin/env python3

"""Behavior tests for isolated parallel split-wheel packaging."""

import os
import pathlib
import signal
import shutil
import subprocess
import tempfile
import time
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PACKAGE_SCRIPT = REPO_ROOT / "scripts" / "package_python_wheels.sh"


class ParallelWheelPackagingTest(unittest.TestCase):
    def test_heavy_wheels_run_in_parallel_and_collect_all_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            api_dir = root / "api"
            python_dir = api_dir / "python"
            output_dir = root / "output"
            fake_python = root / "fake-python"
            python_dir.mkdir(parents=True)
            output_dir.mkdir()
            (root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            (python_dir / "setup.py").write_text("# fake setup entrypoint\n", encoding="utf-8")
            fake_python.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "case \"${SETUP_TYPE:-main}\" in\n"
                "  sdk_cpp|runtime|full) sleep 1 ;;\n"
                "esac\n"
                "mkdir -p dist\n"
                "printf '%s\\n' \"${SETUP_TYPE:-main}\" > \"dist/${SETUP_TYPE:-main}.whl\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)

            started = time.monotonic()
            subprocess.run(
                [
                    "bash",
                    str(PACKAGE_SCRIPT),
                    str(api_dir),
                    str(output_dir),
                    str(fake_python),
                    "python3.11",
                ],
                check=True,
                env={**os.environ, "BUILD_VERSION": "9.9.9"},
            )
            elapsed = time.monotonic() - started

            self.assertLess(elapsed, 2.9)
            self.assertEqual(
                {path.name for path in output_dir.glob("*.whl")},
                {
                    "main.whl",
                    "dashboard.whl",
                    "faas.whl",
                    "sdk_cpp.whl",
                    "runtime.whl",
                    "full.whl",
                },
            )
            self.assertEqual(list(api_dir.glob(".python-wheel-*")), [])

    def test_startup_failure_stops_running_workers_before_cleanup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            api_dir = root / "api"
            python_dir = api_dir / "python"
            output_dir = root / "output"
            bin_dir = root / "bin"
            pid_dir = root / "pids"
            state_file = root / "mktemp-count"
            fake_python = bin_dir / "fake-python"
            fake_mktemp = bin_dir / "mktemp"
            real_mktemp = shutil.which("mktemp")
            self.assertIsNotNone(real_mktemp)
            python_dir.mkdir(parents=True)
            output_dir.mkdir()
            bin_dir.mkdir()
            pid_dir.mkdir()
            (root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
            (python_dir / "setup.py").write_text("# fake setup entrypoint\n", encoding="utf-8")
            fake_python.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "case \"${SETUP_TYPE:-main}\" in\n"
                "  sdk_cpp|runtime|full)\n"
                "    echo $$ > \"$PID_DIR/${SETUP_TYPE}.pid\"\n"
                "    sleep 30\n"
                "    ;;\n"
                "esac\n"
                "mkdir -p dist\n"
                "printf '%s\\n' \"${SETUP_TYPE:-main}\" > \"dist/${SETUP_TYPE:-main}.whl\"\n",
                encoding="utf-8",
            )
            fake_mktemp.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "count=0\n"
                "test ! -f \"$MKTEMP_STATE\" || count=$(cat \"$MKTEMP_STATE\")\n"
                "count=$((count + 1))\n"
                "echo \"$count\" > \"$MKTEMP_STATE\"\n"
                "if test \"$count\" -eq 2; then sleep 1; exit 12; fi\n"
                f'exec "{real_mktemp}" "$@"\n',
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            fake_mktemp.chmod(0o755)

            result = subprocess.run(
                [
                    "bash",
                    str(PACKAGE_SCRIPT),
                    str(api_dir),
                    str(output_dir),
                    str(fake_python),
                    "python3.11",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={
                    **os.environ,
                    "BUILD_VERSION": "9.9.9",
                    "MKTEMP_STATE": str(state_file),
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "PID_DIR": str(pid_dir),
                },
            )

            self.assertNotEqual(result.returncode, 0)
            worker_pid = int((pid_dir / "sdk_cpp.pid").read_text(encoding="utf-8"))
            try:
                os.kill(worker_pid, 0)
            except ProcessLookupError:
                worker_running = False
            else:
                worker_running = True
                os.kill(worker_pid, signal.SIGKILL)
            self.assertFalse(worker_running)
            self.assertEqual(list(api_dir.glob(".python-wheel-*")), [])


if __name__ == "__main__":
    unittest.main()
