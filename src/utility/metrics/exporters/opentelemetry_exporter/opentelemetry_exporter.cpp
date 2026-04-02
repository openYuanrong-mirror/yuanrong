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

#include "metrics/exporters/opentelemetry_exporter/opentelemetry_exporter.h"
#include <nlohmann/json.hpp>
#include "opentelemetry/exporters/otlp/otlp_http_metric_exporter.h"
#include "opentelemetry/sdk/metrics/data/metric_data.h"
#include "opentelemetry/sdk/metrics/export/metric_producer.h"
#include "opentelemetry/sdk/resource/resource.h"
#include "opentelemetry/sdk/instrumentationscope/instrumentation_scope.h"
#include <opentelemetry/sdk/common/global_log_handler.h>
#include <iostream>
#include <fstream>
#include <mutex>


namespace observability {
namespace exporters {
namespace metrics {

namespace {
opentelemetry::exporter::otlp::OtlpHeaders ToOtlpHeaders(const std::map<std::string, std::string>& headers) {
    opentelemetry::exporter::otlp::OtlpHeaders result;
    for (const auto& [key, value] : headers) {
        result.emplace(key, value);
    }
    return result;
}
} // namespace

OpenTelemetryExporter::OpenTelemetryExporter(const std::string& config) {
    // Parse JSON configuration
    try {
        nlohmann::json root = nlohmann::json::parse(config);

        if (root.contains("endpoint")) {
            options_.endpoint = root["endpoint"].get<std::string>();
        }

        if (root.contains("protocol")) {
            options_.protocol = root["protocol"].get<std::string>();
        }

        if (root.contains("timeout")) {
            options_.timeout = std::chrono::milliseconds(root["timeout"].get<uint64_t>());
        }

        if (root.contains("headers")) {
            for (auto& [key, value] : root["headers"].items()) {
                options_.headers[key] = value.get<std::string>();
            }
        }

        if (root.contains("export_mode")) {
            options_.export_mode = root["export_mode"].get<std::string>();
        }

        if (root.contains("batch_size")) {
            options_.batch_size = root["batch_size"].get<uint32_t>();
        }

        if (root.contains("batch_interval")) {
            options_.batch_interval = root["batch_interval"].get<uint32_t>();
        }
    } catch (...) {
        // Use default configuration if parsing fails
    }

    // Create OpenTelemetry HTTP metric exporter
    opentelemetry::exporter::otlp::OtlpHttpMetricExporterOptions otlp_options;
    otlp_options.url = options_.endpoint;
    otlp_options.timeout = options_.timeout;
    otlp_options.http_headers = ToOtlpHeaders(options_.headers);
    otlp_options.content_type = opentelemetry::exporter::otlp::HttpRequestContentType::kBinary;
    otlp_exporter_ = std::make_unique<opentelemetry::exporter::otlp::OtlpHttpMetricExporter>(otlp_options);
}

OpenTelemetryExporter::OpenTelemetryExporter(const OpenTelemetryExporterOptions& options)
    : options_(options) {
    // Create OpenTelemetry HTTP metric exporter
    opentelemetry::exporter::otlp::OtlpHttpMetricExporterOptions otlp_options;
    otlp_options.url = options_.endpoint;
    otlp_options.timeout = options_.timeout;
    otlp_options.http_headers = ToOtlpHeaders(options_.headers);
    otlp_options.content_type = opentelemetry::exporter::otlp::HttpRequestContentType::kBinary;
    otlp_exporter_ = std::make_unique<opentelemetry::exporter::otlp::OtlpHttpMetricExporter>(otlp_options);
}

ExportResult OpenTelemetryExporter::Export(
    const std::vector<observability::sdk::metrics::MetricData>& data) noexcept {
    // Convert MetricData to opentelemetry::sdk::metrics::MetricData
    std::vector<opentelemetry::sdk::metrics::MetricData> otel_data;
    for (const auto& metric : data) {
        opentelemetry::sdk::metrics::MetricData otel_metric;

        // Set instrument descriptor
        otel_metric.instrument_descriptor.name_ = metric.instrumentDescriptor.name;
        otel_metric.instrument_descriptor.description_ = metric.instrumentDescriptor.description;
        otel_metric.instrument_descriptor.unit_ = metric.instrumentDescriptor.unit;
        otel_metric.instrument_descriptor.type_ = static_cast<opentelemetry::sdk::metrics::InstrumentType>(
            metric.instrumentDescriptor.type);

        // Set aggregation temporality.
        // Internal default is UNSPECIFIED (0); Prometheus exporter ignores UNSPECIFIED sums,
        // so fall back to CUMULATIVE when the source does not specify.
        auto src_temporality = static_cast<opentelemetry::sdk::metrics::AggregationTemporality>(
            metric.aggregationTemporality);
        otel_metric.aggregation_temporality =
            (src_temporality == opentelemetry::sdk::metrics::AggregationTemporality::kUnspecified)
                ? opentelemetry::sdk::metrics::AggregationTemporality::kCumulative
                : src_temporality;

        // Set collection timestamp
        otel_metric.end_ts = metric.collectionTs;

        // Convert point data
        std::vector<opentelemetry::sdk::metrics::PointDataAttributes> otel_points;
        for (const auto& point : metric.pointData) {
            opentelemetry::sdk::metrics::PointDataAttributes otel_point;

            // Convert labels to OpenTelemetry OrderedAttributeMap
            for (const auto& [key, value] : point.labels) {
                otel_point.attributes[key] = value;
            }

            // Convert PointValue to SumPointData
            opentelemetry::sdk::metrics::SumPointData sum_data;
            if (std::holds_alternative<int64_t>(point.value)) {
                sum_data.value_ = static_cast<double>(std::get<int64_t>(point.value));
            } else if (std::holds_alternative<uint64_t>(point.value)) {
                sum_data.value_ = static_cast<double>(std::get<uint64_t>(point.value));
            } else if (std::holds_alternative<double>(point.value)) {
                sum_data.value_ = std::get<double>(point.value);
            }
            sum_data.is_monotonic_ = false;

            otel_point.point_data = std::move(sum_data);
            otel_points.push_back(std::move(otel_point));
        }

        otel_metric.point_data_attr_ = std::move(otel_points);
        otel_data.push_back(std::move(otel_metric));
    }

    if (otel_data.empty()) {
        return ExportResult::EMPTY_DATA;
    }

    // Wrap in ScopeMetrics and ResourceMetrics for the OTel exporter API

    // Create an instrumentation scope identifying this metrics library.
    // The unique_ptr must outlive the Export() call since scope_metrics.scope_
    // holds a raw pointer into it.
    auto scope = opentelemetry::sdk::instrumentationscope::InstrumentationScope::Create(
        "yuanrong-functionsystem-metrics", "1.0.0");

    opentelemetry::sdk::metrics::ScopeMetrics scope_metrics;
    scope_metrics.metric_data_ = std::move(otel_data);
    scope_metrics.scope_ = scope.get();

    std::vector<opentelemetry::sdk::metrics::ScopeMetrics> scope_metrics_vec;
    scope_metrics_vec.push_back(std::move(scope_metrics));

    // Create a Resource with service attributes so the OTLP exporter sends
    // non-empty resource attributes.  resource_ is a raw pointer so the
    // Resource object must outlive the Export() call.
    auto resource = opentelemetry::sdk::resource::Resource::Create(
        opentelemetry::sdk::resource::ResourceAttributes{
            {"service.name", "yuanrong-functionsystem"}
        });

    opentelemetry::sdk::metrics::ResourceMetrics resource_metrics;
    resource_metrics.resource_ = &resource;
    resource_metrics.scope_metric_data_ = std::move(scope_metrics_vec);

    // Export data using OpenTelemetry exporter
    auto result = otlp_exporter_->Export(resource_metrics);
    if (result == opentelemetry::sdk::common::ExportResult::kSuccess) {
        // Only trigger callback when health status changes (false -> true)
        if (!is_healthy_) {
            is_healthy_ = true;
            if (health_callback_) {
                health_callback_(true);
            }
        }
        return ExportResult::SUCCESS;
    } else {
        // Only trigger callback when health status changes (true -> false)
        if (is_healthy_) {
            is_healthy_ = false;
            if (health_callback_) {
                health_callback_(false);
            }
        }
        return ExportResult::FAILURE;
    }
}

observability::sdk::metrics::AggregationTemporality OpenTelemetryExporter::GetAggregationTemporality(
    observability::sdk::metrics::InstrumentType /* instrumentType */) const noexcept {
    return observability::sdk::metrics::AggregationTemporality::CUMULATIVE;
}

bool OpenTelemetryExporter::ForceFlush(std::chrono::microseconds timeout) noexcept {
    return otlp_exporter_->ForceFlush(timeout);
}

bool OpenTelemetryExporter::Shutdown(std::chrono::microseconds timeout) noexcept {
    return otlp_exporter_->Shutdown(timeout);
}

void OpenTelemetryExporter::RegisterOnHealthChangeCb(const std::function<void(bool)>& callback) noexcept {
    health_callback_ = callback;
}

} // namespace metrics
} // namespace exporters
} // namespace observability
