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

yr.exception.YRError
==============================

.. py:exception:: yr.exception.YRError(code=ErrorCode.ERR_INNER_SYSTEM_ERROR, module_code=ModuleCode.RUNTIME, message: str = '', error_info=None, cause=None, stack_trace_infos=None)

    YR 模块中所有自定义异常的基类，用于承载结构化错误信息。

    当异常由底层 C++ 运行时返回的错误信息构造时，``code``、``module_code``、``message`` 和 ``stack_trace_infos`` 会优先从 ``error_info`` 中读取。

    可通过以下属性获取结构化错误信息：

    - ``code``：错误码。
    - ``module_code``：上报错误的模块码。
    - ``message``：错误消息。
    - ``error_info``：底层返回的原始错误信息对象。
    - ``cause``：触发当前异常的原始异常。
    - ``stack_trace_infos``：底层返回的调用栈信息。

    ``YRError`` 及其子类也可以从 ``yr`` 顶层模块导入。
