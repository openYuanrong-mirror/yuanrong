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

#ifndef METRICS_TRANSFER_H
#define METRICS_TRANSFER_H
#include <memory>

#include "src/utility/metrics/api/include/gauge.h"
#include "src/utility/metrics/sdk/include/metrics_data.h"

namespace observability {
namespace metrics {
const std::string METRIC_TYPE_STR []  = { "Counter", "Gauge", "Summary", "Histogram" };
inline MetricValue GetGaugeValue(const std::shared_ptr<BasicMetric> &instrument)
{
    ValueType valueType = instrument->GetValueType();
    switch (valueType) {
        case ValueType::DOUBLE: {
            auto gauge = std::static_pointer_cast<Gauge<double>>(instrument);
            return MetricValue(gauge->Value());
        }
        case ValueType::INT: {
            auto gauge = std::static_pointer_cast<Gauge<int64_t>>(instrument);
            return MetricValue(gauge->Value());
        }
        case ValueType::UINT: {
            auto gauge = std::static_pointer_cast<Gauge<uint64_t>>(instrument);
            return MetricValue(gauge->Value());
        }
        case ValueType::UNKNOWN:
        default:
            return MetricValue();
    }
}

inline MetricValue GetInstrumentValue(const std::shared_ptr<BasicMetric> &instrument)
{
    MetricType metricType = instrument->GetMetricType();
    switch (metricType) {
        case MetricType::GAUGE:
            return GetGaugeValue(instrument);
        case MetricType::COUNTER:
        case MetricType::SUMMARY:
        case MetricType::HISTOGRAM:
        default:
            return MetricValue();
    }
}

inline std::string GetMetricTypeStr(const MetricType type)
{
    return METRIC_TYPE_STR[static_cast<int>(type)];
}
}  // namespace metrics
}  // namespace observability
#endif  // METRICS_TRANSFER_H
