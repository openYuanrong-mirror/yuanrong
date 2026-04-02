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

#ifndef OBSERVABILITY_API_METRICS_OBSERVER_RESULT_H
#define OBSERVABILITY_API_METRICS_OBSERVER_RESULT_H

#include <memory>
#include <vector>
#include <string>
#include <variant>

#include "metrics/api/metric_data.h"

namespace observability::api::metrics {

template <class T>
class ObserveResultT {
public:
    virtual ~ObserveResultT() = default;

    void Observe(std::vector<std::pair<MetricLabels, T>> val)
    {
        value_ = val;
    }

    const std::vector<std::pair<MetricLabels, T>> Value()
    {
        return value_;
    }

private:
    std::vector<std::pair<MetricLabels, T>> value_;
};

using ObserveResult =
    std::variant<std::shared_ptr<ObserveResultT<int64_t>>, std::shared_ptr<ObserveResultT<uint64_t>>,
                 std::shared_ptr<ObserveResultT<double>>>;

}  // namespace observability::api::metrics
#endif // OBSERVABILITY_API_METRICS_OBSERVER_RESULT_H
