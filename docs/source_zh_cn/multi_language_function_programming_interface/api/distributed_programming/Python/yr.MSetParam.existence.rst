.. _existence:

yr.MSetParam.existence
------------------------------------

.. warning::

   ``yr.MSetParam`` 已废弃，仅为兼容历史版本保留。新代码请勿继续使用。

.. py:attribute:: MSetParam.existence
   :type: ExistenceOpt
   :value: 0

   表示是否支持 Key 重复写入。
   可选参数为 ``ExistenceOpt.NONE`` （支持，默认参数）和 ``ExistenceOpt.NX`` （不支持，可选）。
