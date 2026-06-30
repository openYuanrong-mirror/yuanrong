#!/usr/bin/env python3
# coding=UTF-8
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

import os
import tempfile
import unittest
import urllib.parse
from unittest.mock import patch

_HTTPS = "https"
_TEST_HOST = "192.0.2.1"


class TestGetInternalUrls(unittest.TestCase):
    """Tests for SandboxInstance.get_internal_urls() method."""

    def test_single_tcp_port(self):
        """Single TCP port mapping returns correct dict."""
        inst = self._make_instance()
        with patch.dict(os.environ, {
            "YR_INTERNAL_HOST_IP": _TEST_HOST,
            "YR_PORT_FORWARDINGS": "tcp:40001:8080",
        }):
            result = inst.get_internal_urls()
        self.assertEqual(len(result), 1)
        self.assertIn(8080, result)
        self._assert_tcp_url(result[8080], f"{_TEST_HOST}:40001")

    def test_multiple_port_mappings(self):
        """Multiple port mappings all returned with correct container port keys."""
        inst = self._make_instance()
        with patch.dict(os.environ, {
            "YR_INTERNAL_HOST_IP": _TEST_HOST,
            "YR_PORT_FORWARDINGS": "tcp:40001:8080;tcp:40002:9090",
        }):
            result = inst.get_internal_urls()
        self.assertEqual(set(result.keys()), {8080, 9090})
        self._assert_tcp_url(result[8080], f"{_TEST_HOST}:40001")
        self._assert_tcp_url(result[9090], f"{_TEST_HOST}:40002")

    def test_https_protocol(self):
        """HTTPS protocol produces https:// scheme URL."""
        inst = self._make_instance()
        with patch.dict(os.environ, {
            "YR_INTERNAL_HOST_IP": _TEST_HOST,
            "YR_PORT_FORWARDINGS": "https:40001:443",
        }):
            result = inst.get_internal_urls()
        self.assertEqual(len(result), 1)
        self.assertIn(443, result)
        self._assert_https_url(result[443], f"{_TEST_HOST}:40001")

    def test_no_env_vars(self):
        """Missing env vars returns empty dict."""
        inst = self._make_instance()
        with patch.dict(os.environ, {}, clear=True):
            result = inst.get_internal_urls()
        self.assertEqual(result, {})

    def test_missing_host_ip(self):
        """Missing YR_INTERNAL_HOST_IP returns empty dict."""
        inst = self._make_instance()
        with patch.dict(os.environ, {"YR_PORT_FORWARDINGS": "tcp:40001:8080"}, clear=True):
            result = inst.get_internal_urls()
        self.assertEqual(result, {})

    def test_missing_port_forwardings(self):
        """Missing YR_PORT_FORWARDINGS returns empty dict."""
        inst = self._make_instance()
        with patch.dict(os.environ, {"YR_INTERNAL_HOST_IP": _TEST_HOST}, clear=True):
            result = inst.get_internal_urls()
        self.assertEqual(result, {})

    def test_empty_port_forwardings(self):
        """Empty YR_PORT_FORWARDINGS returns empty dict."""
        inst = self._make_instance()
        with patch.dict(os.environ, {
            "YR_INTERNAL_HOST_IP": _TEST_HOST,
            "YR_PORT_FORWARDINGS": "",
        }):
            result = inst.get_internal_urls()
        self.assertEqual(result, {})

    def test_malformed_mapping_skipped(self):
        """Malformed entries (less than 3 parts) are silently skipped."""
        inst = self._make_instance()
        with patch.dict(os.environ, {
            "YR_INTERNAL_HOST_IP": _TEST_HOST,
            "YR_PORT_FORWARDINGS": "badentry;tcp:40001:8080",
        }):
            result = inst.get_internal_urls()
        self.assertIn(8080, result)
        self._assert_tcp_url(result[8080], f"{_TEST_HOST}:40001")

    def test_mixed_protocols(self):
        """Mixed TCP and HTTPS protocols produce correct schemes."""
        inst = self._make_instance()
        with patch.dict(os.environ, {
            "YR_INTERNAL_HOST_IP": _TEST_HOST,
            "YR_PORT_FORWARDINGS": "tcp:40001:8080;https:40002:443",
        }):
            result = inst.get_internal_urls()
        self.assertEqual(set(result.keys()), {8080, 443})
        self._assert_tcp_url(result[8080], f"{_TEST_HOST}:40001")
        self._assert_https_url(result[443], f"{_TEST_HOST}:40002")

    def _make_instance(self):
        """Create a SandboxInstance without triggering @yr.instance decoration."""
        from yr.sandbox.sandbox import SandboxInstance
        inst = object.__new__(SandboxInstance)
        setattr(inst, "_initialized", True)
        inst.working_dir = os.path.join(tempfile.gettempdir(), "test")
        inst.env = {}
        return inst

    def _assert_tcp_url(self, url, expected_host_port):
        """Assert URL has correct host:port and uses a non-HTTPS scheme (tcp protocol)."""
        parsed = urllib.parse.urlparse(url)
        self.assertEqual(parsed.netloc, expected_host_port)
        self.assertNotEqual(parsed.scheme, _HTTPS)

    def _assert_https_url(self, url, expected_host_port):
        """Assert URL has correct host:port and uses HTTPS scheme."""
        parsed = urllib.parse.urlparse(url)
        self.assertEqual(parsed.netloc, expected_host_port)
        self.assertEqual(parsed.scheme, _HTTPS)


if __name__ == '__main__':
    unittest.main()
