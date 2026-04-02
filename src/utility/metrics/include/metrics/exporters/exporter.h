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

#ifndef OBSERVABILITY_EXPORTERS_METRICS_EXPORTER_H
#define OBSERVABILITY_EXPORTERS_METRICS_EXPORTER_H

#include <string>

#include "metrics/sdk/metric_data.h"

namespace observability::exporters::metrics {

enum class ExportResult {
    // Batch was exported successfully.
    SUCCESS = 0,

    // Batch exporting failed, caller must not retry exporting the same batch
    // and the batch must be dropped.
    FAILURE = 1,

    // The collection does not have enough space to receive the export batch.
    FAILURE_FULL = 2,

    // The export() function was passed an invalid argument.
    FAILURE_INVALID_ARGUMENT = 3,

    // Empty data to send.
    EMPTY_DATA = 4,
};

class Exporter {
public:
    virtual ~Exporter() = default;
    virtual ExportResult Export(const std::vector<observability::sdk::metrics::MetricData> &data) noexcept = 0;

    virtual observability::sdk::metrics::AggregationTemporality GetAggregationTemporality(
        observability::sdk::metrics::InstrumentType instrumentType) const noexcept = 0;

    virtual bool ForceFlush(std::chrono::microseconds timeout = (std::chrono::microseconds::max)()) noexcept = 0;

    virtual bool Shutdown(std::chrono::microseconds timeout = std::chrono::microseconds(0)) noexcept = 0;

    virtual void RegisterOnHealthChangeCb(const std::function<void(bool)> &onChange) noexcept = 0;
};

}  // namespace observability::exporters::metrics

#endif