yr.exception.YRValueError
==============================

.. py:exception:: yr.exception.YRValueError(code=ErrorCode.ERR_PARAM_INVALID, module_code=ModuleCode.RUNTIME, message: str = '', error_info=None, cause=None, stack_trace_infos=None)

    结构化参数取值错误。

    ``YRValueError`` 继承自 :doc:`yr.exception.YRError` 和 Python 内置 ``ValueError``。用户可以继续使用 ``except ValueError`` 捕获该异常，也可以使用 ``except yr.YRValueError`` 读取结构化错误字段。
