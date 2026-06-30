yr.exception.YRTimeoutError
==============================

.. py:exception:: yr.exception.YRTimeoutError(code=ErrorCode.ERR_GET_OPERATION_FAILED, module_code=ModuleCode.RUNTIME, message: str = '', error_info=None, cause=None, stack_trace_infos=None)

    结构化超时错误。

    ``YRTimeoutError`` 继承自 :doc:`yr.exception.YRRuntimeError` 和 Python 内置 ``TimeoutError``。用户可以继续使用 ``except TimeoutError`` 或 ``except RuntimeError`` 捕获该异常，也可以使用 ``except yr.YRTimeoutError`` 读取结构化错误字段。
