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

#include <fstream>
#include <iostream>
#include <mutex>

#include <nlohmann/json.hpp>

#include <opentelemetry/exporters/otlp/otlp_http_metric_exporter.h>
#include <opentelemetry/sdk/common/global_log_handler.h>
#include <opentelemetry/sdk/instrumentationscope/instrumentation_scope.h>
#include <opentelemetry/sdk/metrics/data/metric_data.h>
#include <opentelemetry/sdk/metrics/export/metric_producer.h>
#include <opentelemetry/sdk/resource/resource.h>

namespace observability {
namespace exporters {
namespace metrics {

namespace {
namespace YrMetrics = observability::sdk::metrics;
namespace OtelMetrics = opentelemetry::sdk::metrics;

opentelemetry::exporter::otlp::OtlpHeaders ToOtlpHeaders(const std::map<std::string, std::string> &headers)
{
    opentelemetry::exporter::otlp::OtlpHeaders result;
    for (const auto &[key, value] : headers) {
        result.emplace(key, value);
    }
    return result;
}

OtelMetrics::AggregationTemporality ToOtelTemporality(YrMetrics::AggregationTemporality temporality)
{
    auto otelTemporality = static_cast<OtelMetrics::AggregationTemporality>(temporality);
    if (otelTemporality == OtelMetrics::AggregationTemporality::kUnspecified) {
        return OtelMetrics::AggregationTemporality::kCumulative;
    }
    return otelTemporality;
}

OtelMetrics::SumPointData ToOtelSumPointData(const YrMetrics::PointValue &value)
{
    OtelMetrics::SumPointData sumData;
    if (std::holds_alternative<int64_t>(value)) {
        sumData.value_ = static_cast<double>(std::get<int64_t>(value));
    } else if (std::holds_alternative<uint64_t>(value)) {
        sumData.value_ = static_cast<double>(std::get<uint64_t>(value));
    } else if (std::holds_alternative<double>(value)) {
        sumData.value_ = std::get<double>(value);
    }
    sumData.is_monotonic_ = false;
    return sumData;
}

OtelMetrics::PointDataAttributes ToOtelPointData(const YrMetrics::PointData &point)
{
    OtelMetrics::PointDataAttributes otelPoint;
    for (const auto &[key, value] : point.labels) {
        otelPoint.attributes[key] = value;
    }
    otelPoint.point_data = ToOtelSumPointData(point.value);
    return otelPoint;
}

OtelMetrics::MetricData ToOtelMetricData(const YrMetrics::MetricData &metric)
{
    OtelMetrics::MetricData otelMetric;
    otelMetric.instrument_descriptor.name_ = metric.instrumentDescriptor.name;
    otelMetric.instrument_descriptor.description_ = metric.instrumentDescriptor.description;
    otelMetric.instrument_descriptor.unit_ = metric.instrumentDescriptor.unit;
    otelMetric.instrument_descriptor.type_ = static_cast<OtelMetrics::InstrumentType>(metric.instrumentDescriptor.type);
    otelMetric.aggregation_temporality = ToOtelTemporality(metric.aggregationTemporality);
    otelMetric.end_ts = metric.collectionTs;
    for (const auto &point : metric.pointData) {
        otelMetric.point_data_attr_.push_back(ToOtelPointData(point));
    }
    return otelMetric;
}

std::vector<OtelMetrics::MetricData> ToOtelMetricData(const std::vector<YrMetrics::MetricData> &data)
{
    std::vector<OtelMetrics::MetricData> otelData;
    for (const auto &metric : data) {
        otelData.push_back(ToOtelMetricData(metric));
    }
    return otelData;
}
}  // namespace

OpenTelemetryExporter::OpenTelemetryExporter(const std::string &config)
{
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
            for (auto &[key, value] : root["headers"].items()) {
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

OpenTelemetryExporter::OpenTelemetryExporter(const OpenTelemetryExporterOptions &options)
    : options_(options)
{
    // Create OpenTelemetry HTTP metric exporter
    opentelemetry::exporter::otlp::OtlpHttpMetricExporterOptions otlp_options;
    otlp_options.url = options_.endpoint;
    otlp_options.timeout = options_.timeout;
    otlp_options.http_headers = ToOtlpHeaders(options_.headers);
    otlp_options.content_type = opentelemetry::exporter::otlp::HttpRequestContentType::kBinary;
    otlp_exporter_ = std::make_unique<opentelemetry::exporter::otlp::OtlpHttpMetricExporter>(otlp_options);
}

ExportResult OpenTelemetryExporter::Export(
    const std::vector<observability::sdk::metrics::MetricData> &data) noexcept
{
    auto otelData = ToOtelMetricData(data);
    if (otelData.empty()) {
        return ExportResult::EMPTY_DATA;
    }

    // Wrap in ScopeMetrics and ResourceMetrics for the OTel exporter API

    // Create an instrumentation scope identifying this metrics library.
    // The unique_ptr must outlive the Export() call since scope_metrics.scope_
    // holds a raw pointer into it.
    auto scope = opentelemetry::sdk::instrumentationscope::InstrumentationScope::Create(
        "yuanrong-functionsystem-metrics", "1.0.0");

    opentelemetry::sdk::metrics::ScopeMetrics scope_metrics;
    scope_metrics.metric_data_ = std::move(otelData);
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
        UpdateHealth(true);
        return ExportResult::SUCCESS;
    }
    UpdateHealth(false);
    return ExportResult::FAILURE;
}

void OpenTelemetryExporter::UpdateHealth(bool isHealthy) noexcept
{
    if (is_healthy_ == isHealthy) {
        return;
    }
    is_healthy_ = isHealthy;
    if (health_callback_) {
        health_callback_(isHealthy);
    }
}

observability::sdk::metrics::AggregationTemporality OpenTelemetryExporter::GetAggregationTemporality(
    observability::sdk::metrics::InstrumentType /* instrumentType */) const noexcept
{
    return observability::sdk::metrics::AggregationTemporality::CUMULATIVE;
}

bool OpenTelemetryExporter::ForceFlush(std::chrono::microseconds timeout) noexcept
{
    return otlp_exporter_->ForceFlush(timeout);
}

bool OpenTelemetryExporter::Shutdown(std::chrono::microseconds timeout) noexcept
{
    return otlp_exporter_->Shutdown(timeout);
}

void OpenTelemetryExporter::RegisterOnHealthChangeCb(const std::function<void(bool)> &callback) noexcept
{
    health_callback_ = callback;
}

}  // namespace metrics
}  // namespace exporters
}  // namespace observability
