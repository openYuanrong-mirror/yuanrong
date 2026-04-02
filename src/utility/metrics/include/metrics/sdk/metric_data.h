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

#ifndef OBSERVABILITY_SDK_METRICS_METRIC_DATA_H
#define OBSERVABILITY_SDK_METRICS_METRIC_DATA_H

#include <chrono>
#include <list>
#include <variant>
#include <vector>

#include "metrics/api/metric_data.h"
#include "metrics/sdk/instruments.h"

namespace observability::sdk::metrics {

using PointLabels = observability::api::metrics::MetricLabels;
using PointTimeStamp = observability::api::metrics::SystemTimeStamp;
using PointValue = std::variant<int64_t, uint64_t, double>;

struct PointData {
    PointLabels labels;
    PointValue value;
};

struct MetricData {
    InstrumentDescriptor instrumentDescriptor;
    AggregationTemporality aggregationTemporality = AggregationTemporality::UNSPECIFIED;
    PointTimeStamp collectionTs;
    std::vector<PointData> pointData;
};

}  // namespace observability::sdk::metrics
#endif
