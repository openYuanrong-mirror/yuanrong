yr.StatefulInstance
==================

.. currentmodule:: yr

.. py:class:: StatefulInstance

   有状态函数实例的代理对象，提供远程方法调用能力。

   StatefulInstance 是通过 StatefulInstanceCreator 创建的有状态函数实例的句柄，用于调用实例方法、管理实例生命周期等操作。

   .. note::
      
      StatefulInstance 是推荐使用的新名称，替代了原来的 InstanceProxy。InstanceProxy 仍然可用以保持向后兼容性。

   .. rubric:: 方法

   .. autosummary::
      :toctree:

      yr.StatefulInstance.terminate
      yr.StatefulInstance.is_activate