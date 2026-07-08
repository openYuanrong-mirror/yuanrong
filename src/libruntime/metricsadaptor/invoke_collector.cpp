/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2024-2025. All rights reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
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

#include "src/libruntime/metricsadaptor/invoke_collector.h"

#include <vector>

#include "src/dto/config.h"
#include "src/utility/logger/logger.h"

namespace YR {
namespace Libruntime {
namespace {
const char *const DEFAULT_CONCURRENT_METRIC_NAME = "yr_custom_concurrent_num";
const char *const DEFAULT_CONCURRENT_METRIC_DESC = "default runtime concurrent number";
const char *const DEFAULT_INVOKE_METRIC_NAME = "yr_custom_invoke_num";
const char *const DEFAULT_INVOKE_METRIC_DESC = "default runtime invoke number";
const char *const DEFAULT_CUSTOM_METRIC_UNIT = "count";
thread_local std::vector<bool> g_defaultConcurrentMetricReportedStack;

bool IsDefaultConcurrentMetric(const std::string &metricName)
{
    return metricName == DEFAULT_CONCURRENT_METRIC_NAME;
}

bool IsDefaultInvokeMetric(const std::string &metricName)
{
    return metricName == DEFAULT_INVOKE_METRIC_NAME;
}
}  // namespace

InvokeCollector::InvokeCollector(std::shared_ptr<MetricsAdaptor> metricsAdaptor)
    : metricsAdaptor_(std::move(metricsAdaptor))
{}

void InvokeCollector::OnGaugeMutation(const std::string &metricName)
{
    if (!IsDefaultConcurrentMetric(metricName)) {
        return;
    }

    int64_t activeReports = 0;
    if (metricsAdaptor_ != nullptr && activeDefaultConcurrentMetricReports_.load() > 0) {
        activeReports = activeDefaultConcurrentMetricReports_.fetch_sub(1);
        if (activeReports <= 0) {
            activeDefaultConcurrentMetricReports_.fetch_add(1);
        }
    }
    if (metricsAdaptor_ != nullptr && activeReports > 0) {
        GaugeData gauge;
        gauge.name = DEFAULT_CONCURRENT_METRIC_NAME;
        gauge.description = DEFAULT_CONCURRENT_METRIC_DESC;
        gauge.unit = DEFAULT_CUSTOM_METRIC_UNIT;
        gauge.value = 1;
        LogMetricError(metricsAdaptor_->DecreaseGauge(gauge), "rollback default concurrent metric");
        if (!g_defaultConcurrentMetricReportedStack.empty() && g_defaultConcurrentMetricReportedStack.back()) {
            g_defaultConcurrentMetricReportedStack.back() = false;
        } else {
            canceledDefaultConcurrentMetricReports_.fetch_add(1);
        }
    }
    defaultConcurrentMetricOverridden_ = true;
}

void InvokeCollector::OnUInt64CounterMutation(const std::string &metricName)
{
    if (IsDefaultInvokeMetric(metricName)) {
        defaultInvokeMetricOverridden_ = true;
    }
}

bool InvokeCollector::ShouldCollect(const libruntime::MetaData &metaData, const LibruntimeConfig &config) const
{
    if (!metricsAdaptor_ || !(Config::Instance().ENABLE_METRICS() && config.enableMetrics) ||
        config.selfApiType == libruntime::ApiType::Posix) {
        return false;
    }
    return metaData.invoketype() == libruntime::InvokeType::InvokeFunction ||
           metaData.invoketype() == libruntime::InvokeType::InvokeFunctionStateless;
}

void InvokeCollector::BeforeInvoke(const libruntime::MetaData &metaData, const LibruntimeConfig &config)
{
    if (!ShouldCollect(metaData, config)) {
        return;
    }

    bool reportedDefaultConcurrentMetric = false;
    if (!defaultConcurrentMetricOverridden_.load()) {
        GaugeData gauge;
        gauge.name = DEFAULT_CONCURRENT_METRIC_NAME;
        gauge.description = DEFAULT_CONCURRENT_METRIC_DESC;
        gauge.unit = DEFAULT_CUSTOM_METRIC_UNIT;
        gauge.value = 1;
        auto err = metricsAdaptor_->IncreaseGauge(gauge);
        LogMetricError(err, "report default concurrent metric");
        reportedDefaultConcurrentMetric = err.OK();
        if (reportedDefaultConcurrentMetric) {
            activeDefaultConcurrentMetricReports_.fetch_add(1);
        }
    }
    g_defaultConcurrentMetricReportedStack.push_back(reportedDefaultConcurrentMetric);
}

void InvokeCollector::AfterInvoke(const libruntime::MetaData &metaData, const LibruntimeConfig &config)
{
    if (!ShouldCollect(metaData, config)) {
        return;
    }

    bool reportedDefaultConcurrentMetric = false;
    if (!g_defaultConcurrentMetricReportedStack.empty()) {
        reportedDefaultConcurrentMetric = g_defaultConcurrentMetricReportedStack.back();
        g_defaultConcurrentMetricReportedStack.pop_back();
    }

    if (!defaultInvokeMetricOverridden_.load()) {
        UInt64CounterData counter;
        counter.name = DEFAULT_INVOKE_METRIC_NAME;
        counter.description = DEFAULT_INVOKE_METRIC_DESC;
        counter.unit = DEFAULT_CUSTOM_METRIC_UNIT;
        counter.value = 1;
        LogMetricError(metricsAdaptor_->IncreaseUInt64Counter(counter), "report default invoke metric");
    }

    if (reportedDefaultConcurrentMetric) {
        if (canceledDefaultConcurrentMetricReports_.load() > 0) {
            canceledDefaultConcurrentMetricReports_.fetch_sub(1);
            return;
        }
        GaugeData gauge;
        gauge.name = DEFAULT_CONCURRENT_METRIC_NAME;
        gauge.description = DEFAULT_CONCURRENT_METRIC_DESC;
        gauge.unit = DEFAULT_CUSTOM_METRIC_UNIT;
        gauge.value = 1;
        LogMetricError(metricsAdaptor_->DecreaseGauge(gauge), "report default concurrent metric");
        activeDefaultConcurrentMetricReports_.fetch_sub(1);
    }
}

bool InvokeCollector::IsDefaultConcurrentMetricOverridden() const
{
    return defaultConcurrentMetricOverridden_.load();
}

bool InvokeCollector::IsDefaultInvokeMetricOverridden() const
{
    return defaultInvokeMetricOverridden_.load();
}

void InvokeCollector::LogMetricError(const ErrorInfo &err, const std::string &action) const
{
    if (!err.OK()) {
        YRLOG_WARN("failed to {} for runtime {}, code: {}, msg: {}", action, Config::Instance().YR_RUNTIME_ID(),
                   fmt::underlying(err.Code()), err.Msg());
    }
}

}  // namespace Libruntime
}  // namespace YR
