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

#ifndef OBSERVABILITY_OBSERVER_RESULT_T_H
#define OBSERVABILITY_OBSERVER_RESULT_T_H
#include <memory>

#include "src/utility/metrics/sdk/include/metrics_data.h"
namespace observability {
namespace metrics {

template <class T>
class ObserverResultT {
public:
    ~ObserverResultT() = default;

    void Observe(const T &value)
    {
        value_ = value;
    }

    const T Value() const
    {
        return value_;
    }

private:
    T value_;
};

using ObserveResult =
    std::variant<std::shared_ptr<ObserverResultT<int64_t>>, std::shared_ptr<ObserverResultT<uint64_t>>,
                 std::shared_ptr<ObserverResultT<double>>>;

}  // namespace metrics
}  // namespace observability
#endif  // OBSERVABILITY_OBSERVER_RESULT_T_H
