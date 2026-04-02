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

#ifndef OBSERVABILITY_METRICS_DATA_H
#define OBSERVABILITY_METRICS_DATA_H

#include <chrono>
#include <iostream>
#include <map>
#include <sstream>
#include <variant>

namespace observability {
namespace metrics {

using MetricValue = std::variant<uint64_t, int64_t, double>;

inline std::string ToString(const MetricValue &value)
{
    std::stringstream ss;
    std::visit([&ss](const auto &arg) { ss << std::boolalpha << arg; }, value);
    return ss.str();
}

using Labels = std::map<std::string, std::string>;

struct MetricsData {
    Labels labels;
    std::string name;
    std::string description;
    std::string unit;
    std::string metricType;
    std::chrono::system_clock::time_point collectTimeStamp;
    MetricValue metricValue;
};

}  // namespace metrics
}  // namespace observability
#endif  // OBSERVABILITY_METRICS_DATA_H
