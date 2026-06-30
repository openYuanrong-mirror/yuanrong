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

import collections
import string

import pytest

import yr


@pytest.mark.skip(
    reason="No usage scenario."
)
def test_local_invoke(init_yr_with_local_mode):
    @yr.invoke
    def func():
        return 1

    assert yr.get(func.invoke()) == 1


@pytest.mark.smoke
def test_simple_serialization_local_mode(init_yr_with_local_mode):
    primitive_objects = [
        0,
        0.0,
        0.9,
        1 << 62,
        1 << 999,
        b"a",
        "a",
        string.printable,
        "\u262F",
        "hello world",
        "\xff\xfe\x9c\x001\x000\x00",
        True,
        False,
        [],
        (),
        {},
        type,
        int,
        set(),
        collections.OrderedDict([("hello", 1), ("world", 2)]),
        collections.defaultdict(lambda: 0, [("hello", 1), ("world", 2)]),
        collections.defaultdict(lambda: [], [("hello", 1), ("world", 2)]),
        collections.deque([1, 2, 3, "a", "b", "c", 3.5]),
    ]

    composite_objects = (
        [[obj] for obj in primitive_objects]
        + [(obj,) for obj in primitive_objects]
        + [{(): obj} for obj in primitive_objects]
    )

    @yr.invoke
    def f(x):
        return x

    for obj in primitive_objects + composite_objects:
        new_obj_1 = yr.get(f.invoke(obj))
        new_obj_2 = yr.get(yr.put(obj))
        assert obj == new_obj_1
        assert obj == new_obj_2
        if type(obj).__module__ != "numpy":
            assert type(obj) == type(new_obj_1)
            assert type(obj) == type(new_obj_2)
