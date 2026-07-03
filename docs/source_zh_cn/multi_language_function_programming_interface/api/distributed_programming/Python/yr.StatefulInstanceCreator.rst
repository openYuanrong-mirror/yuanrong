yr.StatefulInstanceCreator
=========================

.. currentmodule:: yr

.. py:class:: StatefulInstanceCreator

   有状态函数实例的创建器，用于在远程系统上创建有状态函数实例。

   StatefulInstanceCreator 是 :py:func:`yr.instance` 装饰器返回的对象类型，用于创建可以在 Yuanrong 分布式系统上远程执行的有状态函数实例。

   .. note::
      
      StatefulInstanceCreator 是推荐使用的新名称，替代了原来的 InstanceCreator。InstanceCreator 仍然可用以保持向后兼容性。

   .. rubric:: 方法

   .. autosummary::
      :toctree:

      yr.StatefulInstanceCreator.invoke
      yr.StatefulInstanceCreator.options
      yr.StatefulInstanceCreator.get_instance