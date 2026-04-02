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

#pragma once

#include "metrics/exporters/exporter.h"
#include <string>
#include <vector>
#include <map>
#include <chrono>

// OpenTelemetry headers
#include "opentelemetry/exporters/otlp/otlp_http_metric_exporter.h"

namespace observability {
namespace exporters {
namespace metrics {

struct OpenTelemetryExporterOptions {
    std::string endpoint = "http://localhost:4318/v1/metrics";
    std::string protocol = "http";
    std::chrono::milliseconds timeout = std::chrono::milliseconds(10000);
    std::map<std::string, std::string> headers;
    std::string export_mode = "BATCH";
    uint32_t batch_size = 100;
    uint32_t batch_interval = 5;
};

class OpenTelemetryExporter : public Exporter {
public:
    OpenTelemetryExporter(const std::string& config);
    OpenTelemetryExporter(const OpenTelemetryExporterOptions& options);

    ExportResult Export(const std::vector<observability::sdk::metrics::MetricData>& data) noexcept override;
    observability::sdk::metrics::AggregationTemporality GetAggregationTemporality(
        observability::sdk::metrics::InstrumentType instrumentType) const noexcept override;
    bool ForceFlush(std::chrono::microseconds) noexcept override;
    bool Shutdown(std::chrono::microseconds) noexcept override;
    void RegisterOnHealthChangeCb(const std::function<void(bool)>&) noexcept override;

private:
    OpenTelemetryExporterOptions options_;
    std::function<void(bool)> health_callback_;
    bool is_healthy_ = false;

    // OpenTelemetry-C++ exporter
    std::unique_ptr<opentelemetry::exporter::otlp::OtlpHttpMetricExporter> otlp_exporter_;
};

} // namespace metrics
} // namespace exporters
} // namespace observability
