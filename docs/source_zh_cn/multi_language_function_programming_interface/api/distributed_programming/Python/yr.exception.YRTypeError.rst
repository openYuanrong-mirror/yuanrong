yr.exception.YRTypeError
==============================

.. py:exception:: yr.exception.YRTypeError(code=ErrorCode.ERR_PARAM_INVALID, module_code=ModuleCode.RUNTIME, message: str = '', error_info=None, cause=None, stack_trace_infos=None)

    结构化参数类型错误。

    ``YRTypeError`` 继承自 :doc:`yr.exception.YRError` 和 Python 内置 ``TypeError``。用户可以继续使用 ``except TypeError`` 捕获该异常，也可以使用 ``except yr.YRTypeError`` 读取结构化错误字段。
