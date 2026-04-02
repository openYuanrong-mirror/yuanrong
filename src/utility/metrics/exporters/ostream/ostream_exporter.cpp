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

#include "metrics/exporters/ostream/ostream_exporter.h"

namespace observability::exporters::metrics {
namespace MetricsSdk = observability::sdk::metrics;
namespace MetricsExporter = observability::exporters::metrics;

std::string OStreamExporter::InstrumentTypeToString(const MetricsSdk::InstrumentType &type) const noexcept
{
    std::string name;
    switch (type) {
        case MetricsSdk::InstrumentType::COUNTER:
            name = "Counter";
            break;
        case MetricsSdk::InstrumentType::GAUGE:
            name = "Gauge";
            break;
        case MetricsSdk::InstrumentType::HISTOGRAM:
            name = "Histogram";
            break;
        default:
            name = "Unknown";
    }
    return name;
}

void OStreamExporter::PrintPointValue(const MetricsSdk::PointValue &val) noexcept
{
    sout_ << "\n    \"Value\": ";
    do {
        if (std::holds_alternative<double>(val)) {
            sout_ << std::to_string(std::get<double>(val));
            break;
        }
        if (std::holds_alternative<uint64_t>(val)) {
            sout_ << std::to_string(std::get<uint64_t>(val));
            break;
        }
        if (std::holds_alternative<int64_t>(val)) {
            sout_ << std::to_string(std::get<int64_t>(val));
            break;
        }
    } while (0);
    sout_ << ",";
}

void OStreamExporter::PrintPointLabels(const MetricsSdk::PointLabels &labels) noexcept
{
    bool isLast = false;
    sout_ << "\n    \"labels\": [{";
    for (const auto &kv : labels) {
        sout_ << "\n      \"" << kv.first << "\": \"" << kv.second << "\"";

        isLast = (&kv == &labels.back());
        if (!isLast) {
            sout_ << ",";
        }
    }
    sout_ << "\n    }]";
}

void OStreamExporter::PrintMetricData(const MetricsSdk::MetricData &data) noexcept
{
    std::lock_guard<std::mutex> lock{ mutex_ };
    sout_ << "{";
    sout_ << "\n  \"Name\": \"" << data.instrumentDescriptor.name << "\",";
    sout_ << "\n  \"Description\": \"" << data.instrumentDescriptor.description << "\",";
    sout_ << "\n  \"Unit\": \"" << data.instrumentDescriptor.unit << "\",";

    auto timeInfo = std::to_string(
        std::chrono::time_point_cast<std::chrono::milliseconds>(data.collectionTs).time_since_epoch().count());
    sout_ << "\n  \"TimeStamp\": \"" << timeInfo << "\",";
    sout_ << "\n  \"Type\": \"" << InstrumentTypeToString(data.instrumentDescriptor.type) << "\",";

    bool isLast = false;
    sout_ << "\n  \"Data\": [";
    for (const auto &point : data.pointData) {
        sout_ << "\n  {";
        PrintPointValue(point.value);
        PrintPointLabels(point.labels);
        sout_ << "\n  }";
        isLast = (&point == &data.pointData.back());
        if (!isLast) {
            sout_ << ",";
        }
    }
    sout_ << "\n  ]";

    sout_ << "\n}\n";
}

MetricsExporter::ExportResult OStreamExporter::Export(const std::vector<MetricsSdk::MetricData> &metricDataVec) noexcept
{
    for (const auto &d : metricDataVec) {
        PrintMetricData(d);
    }
    ForceFlush();
    return MetricsExporter::ExportResult::SUCCESS;
}

MetricsSdk::AggregationTemporality OStreamExporter::GetAggregationTemporality(
    MetricsSdk::InstrumentType instrumentType) const noexcept
{
    switch (instrumentType) {
        case MetricsSdk::InstrumentType::GAUGE:
        case MetricsSdk::InstrumentType::COUNTER:
            return observability::sdk::metrics::AggregationTemporality::DELTA;
        case MetricsSdk::InstrumentType::HISTOGRAM:
        default:
            return observability::sdk::metrics::AggregationTemporality::CUMULATIVE;
    }
}

void OStreamExporter::RegisterOnHealthChangeCb(const std::function<void(bool)>& /* onChange */) noexcept
{
}

bool OStreamExporter::ForceFlush(std::chrono::microseconds /* timeout */) noexcept
{
    (void)sout_.flush();
    return true;
}

bool OStreamExporter::Shutdown(std::chrono::microseconds /* timeout */) noexcept
{
    ForceFlush();
    return true;
}
}  // namespace observability::exporters::metrics
