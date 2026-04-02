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

#ifndef OBSERVIBILITY_OSTREAM_EXPORTER_H
#define OBSERVIBILITY_OSTREAM_EXPORTER_H

#include <iostream>
#include <mutex>

#include "metrics/exporters/exporter.h"

namespace observability::exporters::metrics {
namespace MetricsSdk = observability::sdk::metrics;
namespace MetricsExporter = observability::exporters::metrics;

class OStreamExporter : public observability::exporters::metrics::Exporter {
public:
    explicit OStreamExporter(std::ostream &sout = std::cout) : sout_(sout) {}
    MetricsExporter::ExportResult Export(const std::vector<MetricsSdk::MetricData> &metricDataVec) noexcept override;
    MetricsSdk::AggregationTemporality GetAggregationTemporality(MetricsSdk::InstrumentType instrumentType) const
        noexcept override;
    bool ForceFlush(std::chrono::microseconds timeout = (std::chrono::microseconds::max)()) noexcept override;
    bool Shutdown(std::chrono::microseconds timeout = std::chrono::microseconds(0)) noexcept override;
    void RegisterOnHealthChangeCb(const std::function<void(bool)> &onChange) noexcept override;

private:
    void PrintMetricData(const MetricsSdk::MetricData &data) noexcept;
    std::string InstrumentTypeToString(const MetricsSdk::InstrumentType &type) const noexcept;
    void PrintPointValue(const MetricsSdk::PointValue &val) noexcept;
    void PrintPointLabels(const MetricsSdk::PointLabels &labels) noexcept;

    std::ostream &sout_;
    std::mutex mutex_;
};
} // namespace observability::exporters::metrics
#endif // OBSERVIBILITY_OSTREAM_EXPORTER_H