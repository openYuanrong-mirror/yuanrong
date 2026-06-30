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

import json
import logging
import unittest
from unittest.mock import patch, MagicMock

logger = logging.getLogger(__name__)

META_PREFIX_LEN = 16  # len("0000000000000000")


class TestInitContextInvokeTraceId(unittest.TestCase):
    """
    init_context_invoke requires _ENV_STORAGE to be set up first.
    Call load_context_meta before each test, matching the pattern in test_functionsdk.py.
    """

    def setUp(self):
        from yr.functionsdk import context

        context_meta = {
            "funcMetaData": {"timeout": "3"},
            "extendedMetaData": {"pre_stop": {"pre_stop_timeout": 10}},
        }
        with patch("yr.log.get_logger", return_value=logger):
            context.load_context_meta(context_meta)

    def test_prefers_x_trace_id(self):
        """init_context_invoke should use X-Trace-Id when present."""
        from yr.functionsdk.context import init_context_invoke

        header = {
            "X-Trace-Id": "job-fa60ccbb-trace-adc3f0b94c89457e8fedce36c0d0dc20",
            "X-Request-Id": "some-other-id",
        }
        ctx = init_context_invoke("invoke", header)
        self.assertEqual(
            ctx.get_trace_id(), "job-fa60ccbb-trace-adc3f0b94c89457e8fedce36c0d0dc20"
        )

    def test_falls_back_to_x_request_id(self):
        """Falls back to X-Request-Id when X-Trace-Id is absent."""
        from yr.functionsdk.context import init_context_invoke

        header = {"X-Request-Id": "req-uuid-123"}
        ctx = init_context_invoke("invoke", header)
        self.assertEqual(ctx.get_trace_id(), "req-uuid-123")


class TestGetTraceId(unittest.TestCase):
    def test_prefers_x_trace_id(self):
        from yr.executor.faas_executor import get_trace_id

        headers = {
            "X-Trace-Id": "job-fa60ccbb-trace-adc3f0b94c89457e8fedce36c0d0dc20",
            "X-Request-Id": "req-uuid-123",
        }
        self.assertEqual(
            get_trace_id(headers), "job-fa60ccbb-trace-adc3f0b94c89457e8fedce36c0d0dc20"
        )

    def test_falls_back_to_x_request_id(self):
        from yr.executor.faas_executor import get_trace_id

        self.assertEqual(get_trace_id({"X-Request-Id": "req-uuid-123"}), "req-uuid-123")

    def test_returns_empty_when_no_headers(self):
        from yr.executor.faas_executor import get_trace_id

        self.assertEqual(get_trace_id({}), "")


class TestTransformCallResponseTraceId(unittest.TestCase):
    def test_includes_trace_id_when_provided(self):
        from yr.executor.faas_executor import transform_call_response_to_str
        from yr.functionsdk.error_code import FaasErrorCode

        result_str = transform_call_response_to_str(
            "error msg",
            FaasErrorCode.ENTRY_EXCEPTION,
            trace_id="job-fa60ccbb-trace-adc3f0b94c89457e8fedce36c0d0dc20",
        )
        data = json.loads(result_str[META_PREFIX_LEN:])
        self.assertEqual(
            data.get("traceId"), "job-fa60ccbb-trace-adc3f0b94c89457e8fedce36c0d0dc20"
        )

    def test_omits_trace_id_when_empty(self):
        from yr.executor.faas_executor import transform_call_response_to_str
        from yr.functionsdk.error_code import FaasErrorCode

        result_str = transform_call_response_to_str(
            "error msg", FaasErrorCode.ENTRY_EXCEPTION
        )
        data = json.loads(result_str[META_PREFIX_LEN:])
        self.assertNotIn("traceId", data)


class TestTransformInitResponseTraceId(unittest.TestCase):
    def test_includes_trace_id_on_error(self):
        from yr.executor.faas_executor import transform_init_response_to_str
        from yr.functionsdk.error_code import FaasErrorCode

        result_str = transform_init_response_to_str(
            "init failed",
            FaasErrorCode.INIT_FUNCTION_FAIL,
            trace_id="job-fa60ccbb-trace-adc3f0b94c89457e8fedce36c0d0dc20",
        )
        data = json.loads(result_str)
        self.assertEqual(
            data.get("traceId"), "job-fa60ccbb-trace-adc3f0b94c89457e8fedce36c0d0dc20"
        )

    def test_omits_trace_id_when_empty(self):
        from yr.executor.faas_executor import transform_init_response_to_str
        from yr.functionsdk.error_code import FaasErrorCode

        result_str = transform_init_response_to_str(
            "init failed", FaasErrorCode.INIT_FUNCTION_FAIL
        )
        data = json.loads(result_str)
        self.assertNotIn("traceId", data)


if __name__ == "__main__":
    unittest.main()
