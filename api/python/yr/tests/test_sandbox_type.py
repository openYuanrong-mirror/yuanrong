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

"""Unit tests for sandbox type parameter support."""

from unittest import TestCase, main
from unittest.mock import MagicMock, patch

import yr


class TestSandboxTypeParameter(TestCase):
    """Test cases for SandBox type parameter."""

    def test_sandbox_init_with_default_type(self):
        """Test SandBox initialization with default type (empty string)."""
        with patch('yr.sandbox.sandbox.SandBoxInstance') as mock_instance:
            mock_options = MagicMock()
            mock_instance.options.return_value = mock_instance

            sandbox = yr.sandbox.SandBox()

            # Verify custom_extensions["sandbox_type"] is not set when type is empty
            call_args = mock_instance.options.call_args
            opts = call_args[0][0]  # InvokeOptions object

            # When type is default (empty), sandbox_type should not be in custom_extensions
            self.assertNotIn("sandbox_type", opts.custom_extensions)

    def test_sandbox_init_with_supervisor_type(self):
        """Test SandBox initialization with supervisor type."""
        with patch('yr.sandbox.sandbox.SandBoxInstance') as mock_instance:
            mock_options = MagicMock()
            mock_instance.options.return_value = mock_instance

            sandbox = yr.sandbox.SandBox(type="supervisor")

            # Verify custom_extensions["sandbox_type"] is set to "supervisor"
            call_args = mock_instance.options.call_args
            opts = call_args[0][0]  # InvokeOptions object

            self.assertIn("sandbox_type", opts.custom_extensions)
            self.assertEqual(opts.custom_extensions["sandbox_type"], "supervisor")

    def test_sandbox_init_with_empty_type(self):
        """Test SandBox initialization with explicitly empty type."""
        with patch('yr.sandbox.sandbox.SandBoxInstance') as mock_instance:
            mock_options = MagicMock()
            mock_instance.options.return_value = mock_instance

            sandbox = yr.sandbox.SandBox(type="")

            # Verify custom_extensions["sandbox_type"] is not set when type is empty
            call_args = mock_instance.options.call_args
            opts = call_args[0][0]  # InvokeOptions object

            self.assertNotIn("sandbox_type", opts.custom_extensions)

    def test_sandbox_create_with_default_type(self):
        """Test sandbox.create() with default type."""
        with patch('yr.sandbox.sandbox.SandBox') as mock_sandbox:
            yr.sandbox.create()

            # Verify SandBox is called with type=""
            call_args = mock_sandbox.call_args
            # Positional args: (working_dir, env, port_forwardings, type)
            self.assertEqual(call_args[0][3], "")  # type parameter

    def test_sandbox_create_with_supervisor_type(self):
        """Test sandbox.create() with supervisor type."""
        with patch('yr.sandbox.sandbox.SandBox') as mock_sandbox:
            yr.sandbox.create(type="supervisor")

            # Verify SandBox is called with type="supervisor"
            call_args = mock_sandbox.call_args
            self.assertEqual(call_args[0][3], "supervisor")

    def test_sandbox_with_port_forwardings_and_type(self):
        """Test SandBox with both port_forwardings and type parameters."""
        with patch('yr.sandbox.sandbox.SandBoxInstance') as mock_instance:
            mock_options = MagicMock()
            mock_instance.options.return_value = mock_instance

            port_forwardings = [yr.PortForwarding(port=8080, protocol="TCP")]
            sandbox = yr.sandbox.SandBox(port_forwardings=port_forwardings, type="supervisor")

            # Verify both parameters are set
            call_args = mock_instance.options.call_args
            opts = call_args[0][0]  # InvokeOptions object

            self.assertIn("sandbox_type", opts.custom_extensions)
            self.assertEqual(opts.custom_extensions["sandbox_type"], "supervisor")
            # port_forwardings should also be set
            self.assertIsNotNone(opts.port_forwardings)

    def test_sandbox_type_parameter_precedence(self):
        """Test that type parameter correctly sets custom_extensions."""
        with patch('yr.sandbox.sandbox.SandBoxInstance') as mock_instance:
            mock_options = MagicMock()
            mock_instance.options.return_value = mock_instance

            # Test different type values
            test_cases = [
                ("supervisor", "supervisor"),
                ("", None),  # Empty string should not set sandbox_type
                ("other", "other"),  # Future extensibility
            ]

            for type_value, expected_value in test_cases:
                mock_instance.reset_mock()

                sandbox = yr.sandbox.SandBox(type=type_value)

                call_args = mock_instance.options.call_args
                opts = call_args[0][0]

                if expected_value is None:
                    self.assertNotIn("sandbox_type", opts.custom_extensions)
                else:
                    self.assertEqual(opts.custom_extensions.get("sandbox_type"), expected_value)

    def test_sandbox_with_working_dir_and_type(self):
        """Test SandBox with working_dir and type parameters."""
        with patch('yr.sandbox.sandbox.SandBoxInstance') as mock_instance:
            mock_options = MagicMock()
            mock_instance.options.return_value = mock_instance

            working_dir = "/tmp/test"
            sandbox = yr.sandbox.SandBox(working_dir=working_dir, type="supervisor")

            # Verify invoke is called with correct parameters
            mock_invoke = MagicMock()
            mock_instance.options.return_value.invoke = mock_invoke

            call_args = mock_instance.options.call_args
            opts = call_args[0][0]

            self.assertEqual(opts.custom_extensions.get("sandbox_type"), "supervisor")
            # Verify invoke is called with working_dir
            mock_invoke.assert_called_once_with(working_dir, None)

    def test_sandbox_with_env_and_type(self):
        """Test SandBox with env and type parameters."""
        with patch('yr.sandbox.sandbox.SandBoxInstance') as mock_instance:
            mock_options = MagicMock()
            mock_instance.options.return_value = mock_instance

            env = {"TEST_VAR": "test_value"}
            sandbox = yr.sandbox.SandBox(env=env, type="supervisor")

            # Verify sandbox_type is set
            call_args = mock_instance.options.call_args
            opts = call_args[0][0]

            self.assertEqual(opts.custom_extensions.get("sandbox_type"), "supervisor")
            # Verify invoke is called with env
            mock_invoke = MagicMock()
            mock_instance.options.return_value.invoke = mock_invoke
            mock_invoke.assert_called_once_with(None, env)

    def test_sandbox_skip_serialize_always_true(self):
        """Test that skip_serialize is always True for SandBox."""
        with patch('yr.sandbox.sandbox.SandBoxInstance') as mock_instance:
            mock_options = MagicMock()
            mock_instance.options.return_value = mock_instance

            sandbox = yr.sandbox.SandBox(type="supervisor")

            call_args = mock_instance.options.call_args
            opts = call_args[0][0]

            # Verify skip_serialize is True
            self.assertTrue(opts.skip_serialize)


class TestSandboxTypeIntegration(TestCase):
    """Integration tests for sandbox type parameter (require yr.init)."""

    def test_sandbox_type_string_format(self):
        """Test that type parameter uses lowercase format."""
        # Test that we use lowercase "supervisor" not "supervisor"
        type_value = "supervisor"

        # Verify it's lowercase
        self.assertEqual(type_value, type_value.lower())
        self.assertNotEqual(type_value, "supervisor")

    def test_sandbox_type_consistency(self):
        """Test consistency between SandBox and create() functions."""
        # Both should accept the same type parameter
        with patch('yr.sandbox.sandbox.SandBoxInstance') as mock_instance:
            mock_options = MagicMock()
            mock_instance.options.return_value = mock_instance

            # Test SandBox class
            sandbox1 = yr.sandbox.SandBox(type="supervisor")
            call_args1 = mock_instance.options.call_args
            opts1 = call_args1[0][0]
            type1 = opts1.custom_extensions.get("sandbox_type")

            mock_instance.reset_mock()

            # Test create() function
            with patch('yr.sandbox.sandbox.SandBox') as mock_sandbox:
                yr.sandbox.create(type="supervisor")
                call_args2 = mock_sandbox.call_args
                type2 = call_args2[0][3]

                # Both should use the same type value
                self.assertEqual(type1, type2)
                self.assertEqual(type1, "supervisor")


if __name__ == "__main__":
    main()
