.. _get_stream:

yr.Context.get_stream
-------------------------

.. py:method:: Context.get_stream()

    获取 SSE 流对象。

    返回：
        SSE 流对象，返回类型：Stream。使用 Stream.write() 写入数据，参数必须是序列化的 `str`。 
