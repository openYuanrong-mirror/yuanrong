.. Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
..
.. Licensed under the Apache License, Version 2.0 (the "License");
.. you may not use this file except in compliance with the License.
.. You may obtain a copy of the License at
..
.. http://www.apache.org/licenses/LICENSE-2.0
..
.. Unless required by applicable law or agreed to in writing, software
.. distributed under the License is distributed on an "AS IS" BASIS,
.. WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
.. See the License for the specific language governing permissions and
.. limitations under the License.

yr.exception.YRRuntimeError
==============================

.. py:exception:: yr.exception.YRRuntimeError(code=ErrorCode.ERR_INNER_SYSTEM_ERROR, module_code=ModuleCode.RUNTIME, message: str = '', error_info=None, cause=None, stack_trace_infos=None)

    结构化运行时错误。

    ``YRRuntimeError`` 继承自 :doc:`yr.exception.YRError` 和 Python 内置 ``RuntimeError``。用户可以继续使用 ``except RuntimeError`` 捕获该异常，也可以使用 ``except yr.YRRuntimeError`` 读取 ``code``、``module_code``、``message``、``error_info`` 等结构化字段。
