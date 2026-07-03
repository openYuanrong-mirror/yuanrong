#!/usr/bin/env python3
# coding=UTF-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
yr api
"""
# pylint: disable=huawei-wrong-import-position
import importlib
import os
import ctypes
import sys

_NATIVE_PRELOADS = [
    "libsecurec.so",  # securec must before libdatasystem
    "libtbb.so.2",
    "libcrypto.so.3",
    "libcrypto.so.1.1",
    "libssl.so.3",
    "libssl.so.1.1",
    "libds-spdlog.so.1.12.0",
    "libzmq.so.5.2.5",
    "libaddress_sorting.so.42.0.0",
    "libaddress_sorting.so.42",
    "libabseil_dll.so.2407.0.0",
    "libprotobuf.so.25.5.0",
    "librpc_option_protos.so",
    "libcommon_flags.so",
    "libetcdapi_proto.so",
    "libgrpc++.so.1.65",
    "libgrpc.so.42",
    "libupb_json_lib.so.42",
    "libupb_textformat_lib.so.42",
    "libutf8_range_lib.so.42",
    "libupb_message_lib.so.42",
    "libupb_base_lib.so.42",
    "libupb_mem_lib.so.42",
    "libgpr.so.42",
    "libgflags.so.2.2",
    "libbrpc.so",
    "libdatasystem.so",
    "libspdlog.so.1.12.0",
    "libyrlogs.so",
    "liblitebus.so.0.0.1",
    "libobservability-metrics-exporter-ostream.so",
    "libobservability-metrics-file-exporter.so",
    "libobservability-prometheus-push-exporter.so",
    "libobservability-metrics.so",
    "libobservability-metrics-sdk.so",
]
_SYSTEM_LIBRARY_DIRS = ("/usr/lib64", "/usr/lib", "/lib64", "/lib")
_SYSTEM_SSL_PRELOADS = (
    "libcrypto.so.3",
    "libcrypto.so.1.1",
    "libssl.so.3",
    "libssl.so.1.1",
)
_NATIVE_PRELOADED = False
_NATIVE_EXPORT_MODULES = {
    "yr.apis",
    "yr.cluster_mode_runtime",
    "yr.runtime_holder",
    "yr.session_service",
    "yr.functionsdk.context",
}


def _preload_system_library(so_name):
    for lib_dir in _SYSTEM_LIBRARY_DIRS:
        so_path = os.path.join(lib_dir, so_name)
        try:
            ctypes.CDLL(so_path, mode=getattr(ctypes, "RTLD_GLOBAL", 0))
            return True
        except OSError:
            pass
    return False


def _preload_native_libraries():
    """Load bundled runtime libraries only when native runtime APIs are requested."""
    global _NATIVE_PRELOADED
    if _NATIVE_PRELOADED:
        return
    _NATIVE_PRELOADED = True
    yr_dir = os.path.dirname(os.path.realpath(__file__))
    system_preloaded = {
        so_name
        for so_name in _SYSTEM_SSL_PRELOADS
        if _preload_system_library(so_name)
    }
    for so_name in _NATIVE_PRELOADS:
        if so_name in system_preloaded:
            continue
        so_path = os.path.join(yr_dir, so_name)
        try:
            ctypes.CDLL(so_path, mode=getattr(ctypes, "RTLD_GLOBAL", 0))
        except OSError:
            pass


_API_EXPORTS = {
    "init", "finalize", "put", "get", "invoke", "instance", "wait", "cancel", "method", "exit",
    "create_stream_producer", "create_stream_consumer", "delete_stream",
    "kv_read", "kv_write", "kv_del", "kv_set", "kv_get", "kv_get_with_param",
    "kv_m_write_tx", "kv_write_with_param", "get_instance", "is_initialized",
    "query_global_producers_num", "query_global_consumers_num", "save_state", "load_state",
    "cpp_function", "java_function", "go_function", "cpp_instance_class", "java_instance_class",
    "go_instance_class", "resources", "create_resource_group", "remove_resource_group",
    "get_node_ip_address", "list_named_instances", "kill_instance", "restore_from_checkpoint",
    "delete_checkpoint", "list_checkpoints", "StatelessFunction", "StatefulInstance",
    "StatefulInstanceCreator",
}

_LAZY_EXPORTS = {name: ("yr.apis", name) for name in _API_EXPORTS}
_LAZY_EXPORTS.update({
    "fcc": ("yr.fcc", None),
    "create_function_group": ("yr.fcc", "create_function_group"),
    "get_function_group_context": ("yr.fcc", "get_function_group_context"),
    "ResourceGroup": ("yr.resource_group", "ResourceGroup"),
    "ExistenceOpt": ("yr.base_runtime", "ExistenceOpt"),
    "WriteMode": ("yr.base_runtime", "WriteMode"),
    "CacheType": ("yr.base_runtime", "CacheType"),
    "SetParam": ("yr.base_runtime", "SetParam"),
    "MSetParam": ("yr.base_runtime", "MSetParam"),
    "CreateParam": ("yr.base_runtime", "CreateParam"),
    "AlarmSeverity": ("yr.base_runtime", "AlarmSeverity"),
    "AlarmInfo": ("yr.base_runtime", "AlarmInfo"),
    "ConsistencyType": ("yr.base_runtime", "ConsistencyType"),
    "GetParams": ("yr.base_runtime", "GetParams"),
    "GetParam": ("yr.base_runtime", "GetParam"),
    "Config": ("yr.config", "Config"),
    "InvokeOptions": ("yr.config", "InvokeOptions"),
    "UserTLSConfig": ("yr.config", "UserTLSConfig"),
    "FunctionGroupOptions": ("yr.config", "FunctionGroupOptions"),
    "SchedulingAffinityType": ("yr.config", "SchedulingAffinityType"),
    "FunctionGroupContext": ("yr.config", "FunctionGroupContext"),
    "ServerInfo": ("yr.config", "ServerInfo"),
    "DeviceInfo": ("yr.config", "DeviceInfo"),
    "ResourceGroupOptions": ("yr.config", "ResourceGroupOptions"),
    "GroupOptions": ("yr.config", "GroupOptions"),
    "PortForwarding": ("yr.config", "PortForwarding"),
    "SnapstartInfo": ("yr.checkpoint", "SnapstartInfo"),
    "SnapstartResponse": ("yr.checkpoint", "SnapstartResponse"),
    "Group": ("yr.group", "Group"),
    "ProducerConfig": ("yr.stream", "ProducerConfig"),
    "SubscriptionConfig": ("yr.stream", "SubscriptionConfig"),
    "Element": ("yr.stream", "Element"),
    "Function": ("yr.functionsdk.function", "Function"),
    "Context": ("yr.functionsdk.context", "Context"),
    "Affinity": ("yr.affinity", "Affinity"),
    "AffinityType": ("yr.affinity", "AffinityType"),
    "AffinityKind": ("yr.affinity", "AffinityKind"),
    "AffinityScope": ("yr.affinity", "AffinityScope"),
    "LabelOperator": ("yr.affinity", "LabelOperator"),
    "OperatorType": ("yr.affinity", "OperatorType"),
    "Gauge": ("yr.metrics", "Gauge"),
    "Alarm": ("yr.metrics", "Alarm"),
    "UInt64Counter": ("yr.metrics", "UInt64Counter"),
    "DoubleCounter": ("yr.metrics", "DoubleCounter"),
    "CustomGauge": ("yr.metrics", "CustomGauge"),
    "CustomCounter": ("yr.metrics", "CustomCounter"),
    "Histogram": ("yr.metrics", "Histogram"),
    "trace": ("yr.trace", None),
    "FunctionProxy": ("yr.decorator.function_proxy", "FunctionProxy"),
    "InstanceCreator": ("yr.decorator.instance_proxy", "InstanceCreator"),
    "InstanceProxy": ("yr.decorator.instance_proxy", "InstanceProxy"),
    "MethodProxy": ("yr.decorator.instance_proxy", "MethodProxy"),
    "FunctionGroupHandler": ("yr.decorator.instance_proxy", "FunctionGroupHandler"),
    "FunctionGroupMethodProxy": ("yr.decorator.instance_proxy", "FunctionGroupMethodProxy"),
    "DebugServer": ("yr.debug_server.debug_server", "DebugServer"),
    "set_trace": ("yr.debug_server.rpdb", "set_trace"),
    "sandbox": ("yr.sandbox", None),
    "ManagedSessionObj": ("yr.session_service", "ManagedSessionObj"),
    "SessionService": ("yr.session_service", "SessionService"),
    "cluster_mode_runtime": ("yr.cluster_mode_runtime", None),
    "runtime_holder": ("yr.runtime_holder", None),
})


def __getattr__(name):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'yr' has no attribute {name!r}")
    module_name, attr_name = target
    if module_name in _NATIVE_EXPORT_MODULES:
        _preload_native_libraries()
    module = sys.modules.get(module_name)
    if module is None:
        module = importlib.import_module(module_name)
    value = module if attr_name is None else getattr(module, attr_name)
    globals()[name] = value
    return value

__all__ = [
    "init", "finalize", "Config", "UserTLSConfig",
    "put", "get",
    "wait", "cancel", "invoke", "instance", "method", "InvokeOptions", "PortForwarding", "exit",
    "ProducerConfig", "SubscriptionConfig", "Element",
    "create_stream_producer", "create_stream_consumer", "delete_stream",
    "Context", "Function", "GetParam", "GetParams",
    "Affinity", "AffinityType", "AffinityKind", "AffinityScope", "LabelOperator", "OperatorType",
    "kv_read", "kv_write", "kv_set", "kv_get", "kv_get_with_param", "kv_del", "kv_m_write_tx",
    "ExistenceOpt", "WriteMode", "CacheType", "SetParam", "MSetParam", "CreateParam", "ConsistencyType",
    "save_state", "load_state", "get_instance", "is_initialized",
    "query_global_producers_num", "query_global_consumers_num",
    "Gauge", "Alarm", "java_instance_class", "go_instance_class", "fcc", "create_function_group",
    "AlarmSeverity", "AlarmInfo", "UInt64Counter", "DoubleCounter", "CustomGauge", "CustomCounter", "Histogram",
    "trace",
    "FunctionGroupOptions", "SchedulingAffinityType", "FunctionGroupContext", "ServerInfo", "DeviceInfo",
    "get_function_group_context", "create_resource_group", "remove_resource_group", "ResourceGroup",
    "StatelessFunction", "StatefulInstance", "StatefulInstanceCreator",
    "FunctionProxy", "InstanceCreator", "InstanceProxy", "MethodProxy", "FunctionGroupHandler",
    "FunctionGroupMethodProxy", "get_node_ip_address", "list_named_instances", "Group", "GroupOptions",
    "DebugServer", "set_trace", "sandbox", "kill_instance",
    "restore_from_checkpoint", "delete_checkpoint", "list_checkpoints",
    "SnapstartInfo", "SnapstartResponse", "ManagedSessionObj", "SessionService",
    "cluster_mode_runtime",
]
