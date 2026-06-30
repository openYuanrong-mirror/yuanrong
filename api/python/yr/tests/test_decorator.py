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

import logging
from unittest import TestCase, main
from unittest.mock import Mock, patch

from yr.code_manager import CodeManager
from yr.decorator import instance_proxy, function_proxy
from yr.object_ref import ObjectRef
from yr.config import InvokeOptions
from yr.config_manager import ConfigManager
from yr.common.utils import CrossLanguageInfo
from yr.libruntime_pb2 import LanguageType, FunctionMeta


logger = logging.getLogger(__name__)


class TestDecorator(TestCase):

    def setUp(self):
        ConfigManager().bypass_datasystem = None

    def tearDown(self):
        ConfigManager().bypass_datasystem = None

    def test_instance_need_order_auto_default_only_when_unset(self):
        class Actor:
            def ping(self):
                return "pong"

        default_creator = instance_proxy.InstanceCreator.create_from_user_class(Actor, InvokeOptions())
        self.assertTrue(default_creator.__invoke_options__.need_order)

        explicit_false_creator = instance_proxy.InstanceCreator.create_from_user_class(
            Actor, InvokeOptions(need_order=False))
        self.assertFalse(explicit_false_creator.__invoke_options__.need_order)

        with self.assertRaises(ValueError):
            instance_proxy.InstanceCreator.create_from_user_class(
                Actor, InvokeOptions(need_order=True, concurrency=100))

        explicit_true_single_creator = instance_proxy.InstanceCreator.create_from_user_class(
            Actor, InvokeOptions(need_order=True, concurrency=1))
        self.assertTrue(explicit_true_single_creator.__invoke_options__.need_order)

        options_creator = instance_proxy.InstanceCreator.create_from_user_class(Actor)
        options_creator.options(InvokeOptions(need_order=False))
        self.assertFalse(options_creator.__invoke_options__.need_order)

        with self.assertRaises(ValueError):
            options_creator.options(InvokeOptions(need_order=True, concurrency=100))

    @patch("yr.runtime_holder.global_runtime.get_runtime")
    @patch("yr.log.get_logger")
    def test_instance_proxy(self, mock_logger, get_runtime):
        mock_logger.return_value = logger
        mock_runtime = Mock()
        mock_runtime.wait.return_value = (["3", "2", "1"], [])
        mock_runtime.get_instance_by_name.return_value = FunctionMeta()
        mock_runtime.create_instance.return_value = "createIns"
        mock_runtime.terminate_instance.return_value = None
        mock_runtime.terminate_group.return_value = None
        mock_runtime.get_instances.return_value = ["instance1", "instance2"]
        mock_runtime.invoke_instance.return_value = ["obj1"]
        get_runtime.return_value = mock_runtime
        ins_creator = instance_proxy.InstanceCreator()

        class CppClass:
            def __init__(self, class_name: str, factory_name: str, function_urn: str):
                self.__class_name__ = class_name
                self.__factory_name__ = factory_name
                self.__function_urn__ = function_urn

            def get_class_name():
                return "className"

            def get_factory_name():
                return "factoryName"

            def get_function_key():
                return "functionKey"

            def hello(self):
                return "hello"

        ins_creator = ins_creator.create_cpp_user_class(CppClass)
        with self.assertRaises(TypeError):
            ins_creator.options(name=[1])

        with self.assertRaises(ValueError):
            ins_creator.options(name="")

        with self.assertRaises(TypeError):
            ins_creator.options(name="ins", namespace=[1])

        with self.assertRaises(ValueError):
            ins_creator.options(name="ins", namespace="")

        ins_creator = ins_creator.options([InvokeOptions(cpu=1000, need_order=True, concurrency=1)])
        ins1 = ins_creator.invoke()
        self.assertTrue(ins1.need_order)

        print(dir(ins1))

        with self.assertRaises(Exception):
            ins1.is_terminate()

        obj = ins1.get.options(InvokeOptions()).invoke()
        self.assertTrue(isinstance(obj, ObjectRef))

        ConfigManager().bypass_datasystem = True
        ins1.get.options(InvokeOptions(bypass_datasystem=False)).invoke()
        self.assertTrue(mock_runtime.invoke_instance.call_args.kwargs["opt"].bypass_datasystem)
        ConfigManager().bypass_datasystem = None

        ins1.group_name = ""
        with self.assertRaises(RuntimeError):
            ins1.get_function_group_handler()

        ins1.group_name = "group"
        res = ins1.get_function_group_handler()
        self.assertIsInstance(res, instance_proxy.FunctionGroupHandler)

        state = ins1.serialization_(False)
        ins1.deserialization_(state)
        self.assertTrue(ins1.need_order)

        mock_runtime.get_real_instance_id.return_value = "real-instance-id-123"
        mock_runtime.get_real_instance_id.reset_mock()
        self.assertEqual(ins1.real_id, "real-instance-id-123")
        mock_runtime.get_real_instance_id.assert_called_once_with(ins1.instance_id)

        ins1.terminate()
        self.assertFalse(ins1.is_activate())

        with self.assertRaises(RuntimeError):
            instance_proxy.InstanceCreator().create_from_user_class(CppClass, InvokeOptions(name="instance1")).get_instance("instance1")

        mock_runtime.get_instance_by_name.return_value = FunctionMeta()
        get_runtime.return_value = mock_runtime

        ready_ins = instance_proxy.get_instance_by_name("", "", 1)
        self.assertTrue(ready_ins.is_activate())

        with self.assertRaises(RuntimeError):
            decorator = instance_proxy.make_decorator()
            decorator("test")

    @patch("yr.runtime_holder.global_runtime.get_runtime")
    def test_named_instance_create_does_not_probe_existing_instance_by_name(self, get_runtime):
        mock_runtime = Mock()
        mock_runtime.create_instance.return_value = "ns-named"
        get_runtime.return_value = mock_runtime

        class NamedActor:
            pass

        opt = InvokeOptions(name="named", namespace="ns", skip_serialize=True)
        creator = instance_proxy.InstanceCreator.create_from_user_class(NamedActor, opt)
        instance = creator.invoke()

        self.assertEqual(instance.instance_id, "ns-named")
        mock_runtime.create_instance.assert_called_once()
        mock_runtime.get_instance_by_name.assert_not_called()

    @patch("yr.runtime_holder.global_runtime.get_runtime")
    def test_named_instance_create_propagates_existing_instance_failure(self, get_runtime):
        mock_runtime = Mock()
        mock_runtime.create_instance.side_effect = RuntimeError("instance already exists")
        get_runtime.return_value = mock_runtime

        class NamedActor:
            pass

        opt = InvokeOptions(name="named", namespace="ns", skip_serialize=True)
        creator = instance_proxy.InstanceCreator.create_from_user_class(NamedActor, opt)

        with self.assertRaisesRegex(RuntimeError, "instance already exists"):
            creator.invoke()

        mock_runtime.create_instance.assert_called_once()
        mock_runtime.get_instance_by_name.assert_not_called()

    @patch("yr.runtime_holder.global_runtime.get_runtime")
    @patch("yr.log.get_logger")
    def test_function_proxy(self, mock_logger, get_runtime):
        mock_logger.return_value = logger
        mock_runtime = Mock()
        mock_runtime.get.return_value = "hello"
        mock_runtime.invoke_by_name.return_value = ["obj1"]
        get_runtime.return_value = mock_runtime

        def hello():
            return "hello"
        with self.assertRaises(TypeError):
            function_proxy.FunctionProxy(func=hello, return_nums=[1])
        with self.assertRaises(RuntimeError):
            function_proxy.FunctionProxy(func=hello, return_nums=-1)

        fp = function_proxy.FunctionProxy(func=hello, return_nums=1, cross_language_info=CrossLanguageInfo(
            "cppfunc", "funckey", LanguageType.Cpp, "factoryName"))
        self.assertEqual(fp.cross_language_info.function_name, "cppfunc")

        with self.assertRaises(RuntimeError):
            fp()

        state = fp.__getstate__()
        self.assertFalse("_locak" in state)

        fp.options(InvokeOptions())
        fp.set_urn("")
        fp.set_function_group_size(1)
        func = fp.get_original_func()
        self.assertEqual(func(), "hello", func())
        objRef = fp.invoke()
        self.assertTrue(isinstance(objRef, ObjectRef))

        with self.assertRaises(RuntimeError):
            decorator = function_proxy.make_decorator()
            decorator("test")

        cpp_proxy = function_proxy.make_cpp_function_proxy("cppfunc", "key")
        self.assertEqual(cpp_proxy.cross_language_info.function_name, "cppfunc")

        cross_proxy = function_proxy.make_cross_language_function_proxy("cppfunc", "", LanguageType.Cpp)
        self.assertEqual(cross_proxy.cross_language_info.function_name, "cppfunc")

    @patch("yr.runtime_holder.global_runtime.get_runtime")
    @patch("yr.log.get_logger")
    def test_python_instance_create_registers_class_for_get_instance_lookup(self, mock_logger, get_runtime):
        """
        After create_instance, client registers moduleName%%className so yr.get_instance can
        load_code when runtime returns meta without code/codeID (nested class qualnames).
        """
        mock_logger.return_value = logger
        CodeManager().clear()
        try:

            class LocalActor:
                pass

            mock_rt = Mock()
            mock_rt.create_instance.return_value = "ins-1"
            mock_rt.get_instance_by_name.side_effect = RuntimeError("not found")
            get_runtime.return_value = mock_rt

            opts = InvokeOptions(name="actor1", namespace="ns1")
            creator = instance_proxy.InstanceCreator.create_from_user_class(LocalActor, opts)
            desc = creator.user_class_descriptor
            key = desc.module_name + "%%" + desc.class_name

            creator.create_instance_for_testing(opts, "", None, [], None)

            self.assertIs(CodeManager().load(key), LocalActor)
            mock_rt.create_instance.assert_called_once()
        finally:
            CodeManager().clear()

    @patch("yr.runtime_holder.global_runtime.get_runtime")
    @patch("yr.log.get_logger")
    def test_inner_create_skip_serialize_uses_short_class_name_in_meta(self, mock_logger, get_runtime):
        """skip_serialize: className in FunctionMeta is __name__, not qualname (pre-deploy path)."""
        mock_logger.return_value = logger
        CodeManager().clear()
        try:

            class PredeployActor:
                pass

            mock_rt = Mock()
            mock_rt.create_instance.return_value = "ins-skip"
            mock_rt.get_instance_by_name.side_effect = RuntimeError("not found")
            get_runtime.return_value = mock_rt

            opts = InvokeOptions(name="a1", namespace="")
            opts.skip_serialize = True
            creator = instance_proxy.InstanceCreator.create_from_user_class(PredeployActor, opts)
            qual = creator.__user_class_descriptor__.class_name
            self.assertIn("PredeployActor", qual)

            creator.create_instance_for_testing(opts, "", None, [], None)

            _ca = mock_rt.create_instance.call_args
            func_meta = (_ca.kwargs or _ca[1])["func_meta"]
            self.assertEqual(func_meta.className, "PredeployActor")
            self.assertNotEqual(func_meta.className, qual)

            key = creator.__user_class_descriptor__.module_name + "%%PredeployActor"
            self.assertIs(CodeManager().load(key), PredeployActor)
        finally:
            CodeManager().clear()

    @patch("yr.decorator.function_proxy.global_runtime.get_runtime")
    @patch("yr.decorator.function_proxy.Serialization")
    @patch("yr.log.get_logger")
    def test_function_proxy_small_serialize_sets_inline_code_on_meta(self, mock_logger, mock_ser_cls, get_runtime):
        """Small serialized payload: FunctionMeta carries inline code without initializing datasystem."""
        mock_logger.return_value = logger
        mock_rt = Mock()
        mock_rt.is_object_existing_in_local.return_value = False
        mock_rt.put_serialized.return_value = "ut-code-ref-id"
        mock_rt.generate_group_name.return_value = ""
        mock_rt.invoke_by_name.return_value = ["obj-ref-1"]
        get_runtime.return_value = mock_rt

        ser_obj = Mock()
        ser_obj.__len__ = Mock(return_value=64)
        ser_obj.to_bytes = Mock(return_value=b"ut-inline-payload")
        mock_ser_cls.return_value.serialize.return_value = ser_obj

        def add(a, b):
            return a + b

        fp = function_proxy.FunctionProxy(func=add, return_nums=1)
        fp.options(InvokeOptions())
        fp.invoke_function_for_testing(fp.invoke_options, add, (1, 2), {})

        mock_rt.invoke_by_name.assert_called_once()
        _ia = mock_rt.invoke_by_name.call_args
        func_meta = (_ia.kwargs or _ia[1])["func_meta"]
        self.assertEqual(func_meta.code, b"ut-inline-payload")
        mock_rt.put_serialized.assert_not_called()

    @patch("yr.runtime_holder.global_runtime.get_runtime")
    def test_function_proxy_respects_global_bypass_override(self, get_runtime):
        mock_runtime = Mock()
        mock_runtime.invoke_by_name.return_value = ["obj1"]
        get_runtime.return_value = mock_runtime

        proxy = function_proxy.make_cpp_function_proxy("cppfunc", "key")
        proxy.options(InvokeOptions(bypass_datasystem=False)).invoke()
        self.assertFalse(mock_runtime.invoke_by_name.call_args.kwargs["opt"].bypass_datasystem)

        ConfigManager().bypass_datasystem = True
        proxy.options(InvokeOptions(bypass_datasystem=False)).invoke()
        self.assertTrue(mock_runtime.invoke_by_name.call_args.kwargs["opt"].bypass_datasystem)

        ConfigManager().bypass_datasystem = False
        proxy.invoke_direct()
        self.assertFalse(mock_runtime.invoke_by_name.call_args.kwargs["opt"].bypass_datasystem)

    @patch("yr.runtime_holder.global_runtime.get_runtime")
    def test_instance_creator_respects_global_bypass_override(self, get_runtime):
        mock_runtime = Mock()
        mock_runtime.create_instance.return_value = "instance-id"
        get_runtime.return_value = mock_runtime

        class Actor:
            pass

        ConfigManager().bypass_datasystem = False
        creator = instance_proxy.InstanceCreator.create_from_user_class(
            Actor, InvokeOptions(skip_serialize=True, bypass_datasystem=True))
        creator.invoke()

        opt = mock_runtime.create_instance.call_args.kwargs["opt"]
        self.assertFalse(opt.bypass_datasystem)

    def test_config_manager_preserves_per_invoke_bypass_without_override(self):
        opt = InvokeOptions(bypass_datasystem=True)

        overridden = ConfigManager().override_bypass_datasystem(opt)

        self.assertIs(overridden, opt)
        self.assertTrue(overridden.bypass_datasystem)


if __name__ == "__main__":
    main()
