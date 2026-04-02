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

#ifndef OBSERVABILITY_API_METRICS_GAUGE_H
#define OBSERVABILITY_API_METRICS_GAUGE_H

#include "metrics/api/metric_data.h"

namespace observability::api::metrics {

template <class T>
class Gauge {
public:
    virtual ~Gauge() = default;
    virtual void Set(const T val) noexcept = 0;
    virtual void Set(const T val, const MetricLabels &labels) noexcept = 0;
    virtual void Set(const T val, const MetricLabels &labels, const SystemTimeStamp &timestamp) noexcept = 0;
};

}  // namespace observability::api::metrics

#endif