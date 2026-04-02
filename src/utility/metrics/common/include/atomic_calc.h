/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#ifndef OBSERVABILITY_ATOMIC_CALC_H
#define OBSERVABILITY_ATOMIC_CALC_H

#include <atomic>

namespace observability {
namespace metrics {

template <typename T>
inline std::atomic<T> &AtomicAdd(std::atomic<T> &value, const T &add)
{
    T desired;
    T expected = value.load(std::memory_order_relaxed);
    do {
        desired = expected + add;
    } while (!value.compare_exchange_weak(expected, desired));
    return value;
}

template <typename T>
inline std::atomic<T> &operator-=(std::atomic<T> &value, const T &val)
{
    return AtomicAdd(value, -val);
}

template <typename T>
inline std::atomic<T> &operator+=(std::atomic<T> &value, const T &val)
{
    return AtomicAdd(value, val);
}

}  // namespace metrics
}  // namespace observability
#endif
