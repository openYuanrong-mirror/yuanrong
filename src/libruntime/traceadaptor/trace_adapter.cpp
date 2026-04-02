/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.
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

#include "trace_adapter.h"

#include <array>
#include <json.hpp>

#include "src/dto/config.h"
#include "src/libruntime/traceadaptor/exporter/log_file_exporter_factory.h"
#include "src/utility/logger/logger.h"

namespace YR {
namespace Libruntime {

constexpr uint32_t TRACE_ID_LENGTH = 32;
constexpr uint32_t SPAN_ID_LENGTH = 16;
constexpr uint32_t TRACE_ID_BUF_LENGTH = 16;
constexpr uint32_t SPAN_ID_BUF_LENGTH = 8;
constexpr uint32_t TRACE_PARENT_PARTS = 4;
constexpr uint32_t TRACE_PARENT_FLAGS_LENGTH = 2;

static inline bool IsHexDecimal(const std::string &str)
{
    return std::all_of(str.begin(), str.end(), ::isxdigit);
}

static bool TraceIdStrToArr(std::string traceID, uint8_t (&arr)[TRACE_ID_BUF_LENGTH])
{
    // cut trace id prefix job-xxxxxxxx-trace-
    (void)traceID.erase(std::remove(traceID.begin(), traceID.end(), '-'), traceID.end());
    if (traceID.size() < TRACE_ID_LENGTH) {
        (void)traceID.append(TRACE_ID_LENGTH - traceID.size(), '0');
    }
    traceID = traceID.substr(traceID.size() - TRACE_ID_LENGTH, TRACE_ID_LENGTH);
    if (!IsHexDecimal(traceID)) {
        YRLOG_WARN("invalid traceID format: {}", traceID);
        return false;
    }
    if (traceID.length() != TRACE_ID_LENGTH && traceID.length() != (TRACE_ID_LENGTH - 1)) {
        YRLOG_WARN("invalid length: {}, traceID: {}", traceID.length(), traceID);
        return false;
    }
    YRLOG_DEBUG("load trace id: {} string to buffer array", traceID);
    int pivot = 0;
    // convert each 2 digits to 1 trace id element
    for (size_t i = 0; i < traceID.length(); i += 2) {
        std::string sub = traceID.substr(i, 2);
        int value = std::stoi(sub, nullptr, 16);
        arr[pivot++] = uint8_t(value);
    }
    return pivot == TRACE_ID_BUF_LENGTH;
}

static bool SpanIdStrToArr(const std::string &spanID, uint8_t (&arr)[SPAN_ID_BUF_LENGTH])
{
    if (spanID.length() != SPAN_ID_LENGTH && spanID.length() != (SPAN_ID_LENGTH - 1)) {
        YRLOG_WARN("invalid length: {}, spanID: {}", spanID.length(), spanID);
        return false;
    }
    if (!IsHexDecimal(spanID)) {
        YRLOG_WARN("invalid spanID format: {}", spanID);
        return false;
    }
    int pivot = 0;
    // convert each 2 digits to 1 span id element
    for (size_t i = 0; i < spanID.length(); i += 2) {
        std::string sub = spanID.substr(i, 2);
        int value = std::stoi(sub, nullptr, 16);
        arr[pivot++] = uint8_t(value);
    }
    return pivot == SPAN_ID_BUF_LENGTH;
}

static bool TrySetParentFromTraceParent(opentelemetry::trace::StartSpanOptions &options, const std::string &traceParent)
{
    if (traceParent.empty()) {
        return false;
    }

    std::array<std::string, TRACE_PARENT_PARTS> parts;
    size_t start = 0;
    for (size_t i = 0; i < TRACE_PARENT_PARTS - 1; ++i) {
        auto end = traceParent.find('-', start);
        if (end == std::string::npos) {
            YRLOG_WARN("invalid traceparent format: {}", traceParent);
            return false;
        }
        parts[i] = traceParent.substr(start, end - start);
        start = end + 1;
    }
    parts[TRACE_PARENT_PARTS - 1] = traceParent.substr(start);
    if (parts[TRACE_PARENT_PARTS - 1].find('-') != std::string::npos) {
        YRLOG_WARN("invalid traceparent format: {}", traceParent);
        return false;
    }
    if (parts[3].length() != TRACE_PARENT_FLAGS_LENGTH || !IsHexDecimal(parts[3])) {
        YRLOG_WARN("invalid traceparent trace flags: {}", traceParent);
        return false;
    }

    uint8_t traceIdArr[TRACE_ID_BUF_LENGTH] = {};
    uint8_t spanIdArr[SPAN_ID_BUF_LENGTH] = {};
    if (!TraceIdStrToArr(parts[1], traceIdArr) || !SpanIdStrToArr(parts[2], spanIdArr)) {
        YRLOG_WARN("failed to parse traceparent: {}", traceParent);
        return false;
    }

    opentelemetry::trace::TraceId optlTraceId(traceIdArr);
    opentelemetry::trace::SpanId optlSpanId(spanIdArr);
    opentelemetry::trace::SpanContext spanContext(optlTraceId, optlSpanId, {}, true);
    if (!spanContext.IsValid()) {
        YRLOG_WARN("traceparent resolved to invalid span context: {}", traceParent);
        return false;
    }
    options.parent = spanContext;
    return true;
}

TraceAdapter::~TraceAdapter() noexcept
{
}

void TraceAdapter::InitTrace(const std::string &serviceName, const bool &enableTrace, const std::string &traceConfig)
{
    enableTrace_ = enableTrace;
    YRLOG_DEBUG("init trace, enableTrace is {}, traceConfig is {}", enableTrace, traceConfig);
    if (!enableTrace_) {
        return;
    }
    std::vector<std::unique_ptr<trace_sdk::SpanProcessor>> processors;
    try {
        auto confJson = nlohmann::json::parse(traceConfig);
        for (auto &element : confJson.items()) {
            if (element.key() == OTLP_GRPC_EXPORTER) {
                if (!element.value().contains("enable") || !element.value().at("enable").get<bool>()) {
                    YRLOG_INFO("Trace exporter {} is not enabled", OTLP_GRPC_EXPORTER);
                    continue;
                }
                if (!element.value().contains("endpoint")
                    || element.value().at("endpoint").get<std::string>().empty()) {
                    YRLOG_INFO("Trace exporter {} endpoint is not valid", OTLP_GRPC_EXPORTER);
                    continue;
                    }
                OtelGrpcExporterConfig config;
                config.endpoint = element.value().at("endpoint").get<std::string>();
                opentelemetry::sdk::trace::BatchSpanProcessorOptions batchSpanProcessorOptions;
                YRLOG_INFO("OtelGrpcExporter is enable, endpoint is {}", config.endpoint);
                processors.push_back(
                    std::unique_ptr<trace_sdk::SpanProcessor>(trace_sdk::BatchSpanProcessorFactory::Create(
                        InitOtlpGrpcExporter(config), batchSpanProcessorOptions)));
            } else if (element.key() == LOG_FILE_EXPORTER) {
                if (!element.value().contains("enable")
                    || !element.value().at("enable").get<bool>()) {
                    YRLOG_INFO("Trace exporter {} is not enabled", LOG_FILE_EXPORTER);
                    continue;
                    }
                opentelemetry::sdk::trace::BatchSpanProcessorOptions batchSpanProcessorOptions;
                YRLOG_INFO("logFileExporter is enable");
                processors.push_back(
                    std::unique_ptr<trace_sdk::SpanProcessor>(trace_sdk::BatchSpanProcessorFactory::Create(
                        InitLogFileExporter(), batchSpanProcessorOptions)));
            }
        }
    } catch (nlohmann::detail::parse_error &e) {
        YRLOG_ERROR("Failed to arse trace config json, error: {}", e.what());
        enableTrace_ = false;
        return;
    } catch (std::exception &e) {
        YRLOG_ERROR("Failed to parse trace config json, error: {}", e.what());
        enableTrace_ = false;
        return;
    }
    if (processors.empty()) {
        YRLOG_WARN("There is no supported exporter in config");
        enableTrace_ = false;
        return;
    }
    opentelemetry::sdk::resource::ResourceAttributes attributes = {
        { opentelemetry::sdk::resource::SemanticConventions::kTelemetrySdkLanguage, "" },
        { opentelemetry::sdk::resource::SemanticConventions::kTelemetrySdkName, "" },
        { opentelemetry::sdk::resource::SemanticConventions::kTelemetrySdkVersion, "" },
        { opentelemetry::sdk::resource::SemanticConventions::kServiceName, serviceName },
    };
    auto provider = opentelemetry::nostd::shared_ptr<trace_api::TracerProvider>(new trace_sdk::TracerProvider(
        std::move(processors), opentelemetry::sdk::resource::Resource::Create(attributes)));
    trace_api::Provider::SetTracerProvider(std::move(provider));
}

void TraceAdapter::ShutDown()
{
    if (!enableTrace_) {
        return;
    }
    YRLOG_INFO("enter traceAdapter shutDown");
    enableTrace_ = false;
    auto provider = trace_api::Provider::GetTracerProvider();
    auto traceProvider = static_cast<trace_sdk::TracerProvider*>(provider.get());
    if (traceProvider != nullptr && !traceProvider->ForceFlush()) {
        YRLOG_WARN("traceProvider shutDown failed");
    }
    opentelemetry::nostd::shared_ptr<trace_api::TracerProvider> none;
    trace_api::Provider::SetTracerProvider(none);
}

void TraceAdapter::SetAttr(const std::string &attr, const std::string &value)
{
    attribute_.insert_or_assign(attr, value);
}

OtelSpan TraceAdapter::StartSpan(const std::string &name, const opentelemetry::common::KeyValueIterable &attributes,
                                 const opentelemetry::trace::SpanContextKeyValueIterable &links,
                                 const opentelemetry::trace::StartSpanOptions &startSpanOptions)
{
    if (enableTrace_) {
        auto tracer = GetTracer();
        if (tracer != nullptr) {
            return tracer->StartSpan(name, attributes, links, startSpanOptions);
        }
    }
    std::shared_ptr<trace_api::Tracer> noopTracer = std::make_shared<trace_api::NoopTracer>();
    return opentelemetry::nostd::shared_ptr<trace_api::Span>(new trace_api::NoopSpan(noopTracer));
}

OtelSpan TraceAdapter::StartSpan(const std::string &name,
                                 const opentelemetry::trace::StartSpanOptions &startSpanOptions)
{
    return StartSpan(name, opentelemetry::common::NoopKeyValueIterable(), opentelemetry::trace::NullSpanContext(),
                     startSpanOptions);
}

OtelSpan TraceAdapter::StartSpan(
    const std::string &name,
    std::vector<std::pair<const std::string, const opentelemetry::common::AttributeValue>> attrs,
    const opentelemetry::trace::StartSpanOptions &startSpanOptions)
{
    // preset system attr
    for (const auto &it : attribute_) {
        attrs.emplace_back(it);
    }
    return StartSpan(name, opentelemetry::common::KeyValueIterableView(attrs), opentelemetry::trace::NullSpanContext(),
                     startSpanOptions);
}

opentelemetry::nostd::shared_ptr<opentelemetry::trace::Tracer> TraceAdapter::GetTracer(const std::string &name,
                                                                                       const std::string &version)
{
    auto provider = opentelemetry::trace::Provider::GetTracerProvider();
    return provider->GetTracer(name, version);
}

std::unique_ptr<opentelemetry::sdk::trace::SpanExporter> TraceAdapter::InitLogFileExporter()
{
    return LogFileExporterFactory::Create();
}

std::unique_ptr<opentelemetry::sdk::trace::SpanExporter> TraceAdapter::InitOtlpGrpcExporter(
    const OtelGrpcExporterConfig &conf)
{
    if (conf.endpoint.empty()) {
        return nullptr;
    }
    opentelemetry::exporter::otlp::OtlpGrpcExporterOptions options;
    options.endpoint = conf.endpoint;
    return opentelemetry::exporter::otlp::OtlpGrpcExporterFactory::Create(options);
}

opentelemetry::trace::StartSpanOptions TraceAdapter::BuildOptWithParent(const std::string &traceID,
                                                                        const std::string &spanID,
                                                                        const std::string &traceParent)
{
    YRLOG_DEBUG("build options with parent, traceID: {}, spanID: {}, traceParent: {}",
                traceID, spanID, traceParent);

    opentelemetry::trace::StartSpanOptions options;
    if (TrySetParentFromTraceParent(options, traceParent)) {
        YRLOG_DEBUG("build parent context from traceparent");
    } else if (!traceID.empty() && !spanID.empty()) {
        uint8_t traceIdArr[TRACE_ID_BUF_LENGTH] = {};
        uint8_t spanIdArr[SPAN_ID_BUF_LENGTH] = {};
        if (!TraceIdStrToArr(traceID, traceIdArr) || !SpanIdStrToArr(spanID, spanIdArr)) {
            YRLOG_WARN("failed to build parent from traceID/spanID, traceID: {}, spanID: {}", traceID, spanID);
            options.start_steady_time = opentelemetry::common::SteadyTimestamp(std::chrono::steady_clock::now());
            return options;
        }
        opentelemetry::trace::TraceId optlTraceId(traceIdArr);
        opentelemetry::trace::SpanId optlSpanId(spanIdArr);
        opentelemetry::trace::SpanContext spanContext(optlTraceId, optlSpanId, {}, false);

        YRLOG_DEBUG("option is valid({})", spanContext.IsValid());

        options.parent = spanContext;
    } else if (!traceID.empty()) {
        YRLOG_DEBUG("traceID exists without parent span, skip synthetic parent");
    } else {
        YRLOG_DEBUG("traceID is empty");
    }

    options.start_steady_time = opentelemetry::common::SteadyTimestamp(std::chrono::steady_clock::now());
    return options;
}

OtelSpan TraceAdapter::StartSpan(
    const std::string &name,
    const std::string &traceID,
    const std::string &spanID,
    std::vector<std::pair<const std::string, const opentelemetry::common::AttributeValue>> attrs)
{
    return StartSpan(name, traceID, spanID, "", std::move(attrs));
}

OtelSpan TraceAdapter::StartSpan(
    const std::string &name,
    const std::string &traceID,
    const std::string &spanID,
    const std::string &traceParent,
    std::vector<std::pair<const std::string, const opentelemetry::common::AttributeValue>> attrs)
{
    YRLOG_DEBUG("start span with traceID and spanID, name: {}, traceID: {}, spanID: {}", name, traceID, spanID);
    auto options = BuildOptWithParent(traceID, spanID, traceParent);
    return StartSpan(name, attrs, options);
}
}
}
