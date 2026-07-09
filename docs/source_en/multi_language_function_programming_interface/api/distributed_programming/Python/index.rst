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

Python
==============================

.. TODO yr_shutdown  generator 

Basic API
---------

.. autosummary::
   :nosignatures:
   :recursive:
   :toctree: ./

   yr.init
   yr.is_initialized
   yr.finalize
   yr.Config
   yr.config.ClientInfo


Stateful & Stateless Function API
-----------------------------------

.. autosummary::
   :nosignatures:
   :toctree: ./

   yr.invoke
   yr.StatelessFunction
   yr.FunctionProxy
   yr.instance
   yr.StatefulInstanceCreator
   yr.StatefulInstance
   yr.InstanceProxy
   yr.method
   yr.MethodProxy
   yr.get_instance
   yr.InstanceCreator
   yr.cancel
   yr.exit
   yr.save_state
   yr.load_state
   yr.InvokeOptions
   yr.list_named_instances


Data Object API
-------------------

.. autosummary::
   :nosignatures:
   :toctree: ./

   yr.put
   yr.get
   yr.wait
   yr.object_ref.ObjectRef


Stream API
-----------------

.. autosummary::
   :nosignatures:
   :toctree: ./

   yr.ProducerConfig
   yr.SubscriptionConfig
   yr.Element
   yr.create_stream_producer
   yr.create_stream_consumer
   yr.delete_stream
   yr.fnruntime.Producer
   yr.fnruntime.Consumer

   
Function Interoperation API
-----------------------------

.. autosummary::
   :nosignatures:
   :toctree: ./

   yr.cpp_function
   yr.cpp_instance_class
   yr.java_function
   yr.java_instance_class


Function Group API
-------------------------

.. autosummary::
   :nosignatures:
   :toctree: ./

   yr.create_function_group
   yr.get_function_group_context
   yr.FunctionGroupOptions
   yr.FunctionGroupContext
   yr.FunctionGroupHandler
   yr.FunctionGroupMethodProxy
   yr.device.DataInfo


Resource Group API
----------------------

.. autosummary::
   :nosignatures:
   :toctree: ./

   yr.create_resource_group
   yr.remove_resource_group
   yr.ResourceGroup
   yr.config.ResourceGroupOptions
   yr.config.SchedulingAffinityType
   yr.config.UserTLSConfig
   yr.config.DeploymentConfig


Group API
----------------------

.. autosummary::
   :nosignatures:
   :toctree: ./

   yr.Group
   yr.config.GroupOptions


KV Cache API
-------------------

.. warning::

   ``yr.kv_m_write_tx`` and ``yr.MSetParam`` are deprecated and retained only for compatibility.
   Do not use them in new code.

.. autosummary::
   :nosignatures:
   :toctree: ./

   yr.kv_write
   yr.kv_write_with_param
   yr.kv_m_write_tx
   yr.kv_read
   yr.kv_del
   yr.kv_set
   yr.kv_get
   yr.kv_get_with_param
   yr.ExistenceOpt
   yr.WriteMode
   yr.CacheType
   yr.ConsistencyType
   yr.GetParam
   yr.GetParams
   yr.SetParam
   yr.MSetParam
   yr.CreateParam


Observability API
--------------------

.. autosummary::
   :nosignatures:
   :toctree: ./

   yr.Gauge
   yr.Alarm
   yr.AlarmInfo
   yr.AlarmSeverity
   yr.DoubleCounter
   yr.UInt64Counter
   yr.resources


Affinity Scheduling
----------------------

.. autosummary::
   :nosignatures:
   :recursive:
   :toctree: ./
   
   yr.affinity.AffinityType
   yr.affinity.AffinityKind
   yr.affinity.OperatorType
   yr.affinity.LabelOperator
   yr.affinity.Affinity


Exceptions
---------------------

.. autosummary::
   :nosignatures:
   :recursive:
   :toctree: ./

   yr.exception.YRError
   yr.exception.YRRuntimeError
   yr.exception.YRTimeoutError
   yr.exception.YRValueError
   yr.exception.YRTypeError
   yr.exception.CancelError
   yr.exception.YRInvokeError
   yr.exception.YRequestError
