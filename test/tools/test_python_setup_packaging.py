#!/usr/bin/env python3
# coding=UTF-8

"""Regression tests for Python setup.py packaging IO shortcuts."""

import contextlib
import gc
import importlib.util
import io
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_DIR = REPO_ROOT / "api" / "python"
PYTHON_SETUP = PYTHON_DIR / "setup.py"


def load_python_setup_module():
    """Load setup.py with setuptools.setup mocked so helpers can be tested."""
    module_name = "yuanrong_python_setup_for_test"
    spec = importlib.util.spec_from_file_location(module_name, PYTHON_SETUP)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(PYTHON_DIR))
    try:
        with mock.patch("setuptools.setup"):
            spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(PYTHON_DIR))
    return module


class PythonSetupPackagingTest(unittest.TestCase):
    def test_loading_setup_module_does_not_leak_version_file(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            load_python_setup_module()
            gc.collect()
        self.assertNotIn("ResourceWarning", stderr.getvalue())

    def test_copy_file_flat_skips_identical_destination(self):
        setup_module = load_python_setup_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            source = temp_path / "source" / "libsame.so"
            target_dir = temp_path / "target"
            target = target_dir / source.name
            source.parent.mkdir()
            target_dir.mkdir()
            source.write_bytes(b"same native payload")
            target.write_bytes(b"same native payload")

            with mock.patch.object(setup_module.shutil, "copy") as copy_mock:
                setup_module.copy_file_flat(str(target_dir), str(source))

            copy_mock.assert_not_called()

    def test_copy_file_flat_hardlinks_new_destination_when_possible(self):
        setup_module = load_python_setup_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            source = temp_path / "source" / "libnative.so"
            target_dir = temp_path / "target"
            target = target_dir / source.name
            source.parent.mkdir()
            source.write_bytes(b"native payload")

            with mock.patch.object(setup_module.shutil, "copy") as copy_mock:
                setup_module.copy_file_flat(str(target_dir), str(source))

            copy_mock.assert_not_called()
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertTrue(os.path.samefile(source, target))

    def test_copy_file_flat_resolves_symlink_sources_before_hardlinking(self):
        setup_module = load_python_setup_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            source_dir = temp_path / "source"
            real_source = source_dir / "libnative.so.1.0.0"
            symlink_source = source_dir / "libnative.so.1"
            target_dir = temp_path / "target"
            target = target_dir / symlink_source.name
            source_dir.mkdir()
            real_source.write_bytes(b"native payload")
            symlink_source.symlink_to(real_source.name)

            with mock.patch.object(setup_module.os, "link", wraps=setup_module.os.link) as link_mock:
                setup_module.copy_file_flat(str(target_dir), str(symlink_source))

            link_mock.assert_called_once_with(os.path.realpath(real_source), str(target), follow_symlinks=True)
            self.assertFalse(target.is_symlink())
            self.assertEqual(target.read_bytes(), real_source.read_bytes())
            self.assertTrue(os.path.samefile(real_source, target))

    def test_copy_file_flat_falls_back_to_copy_when_hardlink_fails(self):
        setup_module = load_python_setup_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            source = temp_path / "source" / "libnative.so"
            target_dir = temp_path / "target"
            target = target_dir / source.name
            source.parent.mkdir()
            source.write_bytes(b"native payload")

            with mock.patch.object(setup_module.os, "link", side_effect=OSError("cross-device")):
                with mock.patch.object(setup_module.shutil, "copy", wraps=setup_module.shutil.copy) as copy_mock:
                    setup_module.copy_file_flat(str(target_dir), str(source))

            copy_mock.assert_called_once()
            self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_copy_file_preserves_relative_path_and_hardlinks_when_possible(self):
        setup_module = load_python_setup_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = pathlib.Path(temp_dir)
            root = temp_path / "runtime"
            source = root / "service" / "cpp" / "libnative.so"
            target_dir = temp_path / "build_lib" / "yr" / "runtime"
            target = target_dir / "service" / "cpp" / source.name
            source.parent.mkdir(parents=True)
            source.write_bytes(b"native payload")

            with mock.patch.object(setup_module.shutil, "copy") as copy_mock:
                setup_module.copy_file(str(target_dir), str(source), str(root))

            copy_mock.assert_not_called()
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertTrue(os.path.samefile(source, target))

    def test_strip_wheel_tests_skips_rewrite_when_tests_are_absent(self):
        setup_module = load_python_setup_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            wheel_path = pathlib.Path(temp_dir) / "openyuanrong-0.0.1-py3-none-any.whl"
            with zipfile.ZipFile(wheel_path, "w") as wheel:
                wheel.writestr("yr/__init__.py", "")
                wheel.writestr("yr/runtime/__init__.py", "")

            with mock.patch.object(setup_module.os, "replace") as replace_mock:
                setup_module.strip_wheel_tests(str(wheel_path))

            replace_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
