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

#include "metrics/sdk/alarm.h"

#include <json.hpp>

#include "src/utility/metrics/common/include/constant.h"
#include "src/utility/metrics/common/include/metric_logger.h"
#include "metrics/sdk/gauge.h"
#include "metrics/sdk/metric_recorder.h"

namespace observability::sdk::metrics {
namespace MetricsApi = observability::api::metrics;

nlohmann::json ConvertEventModel(const observability::api::metrics::AlarmInfo &alarmInfo)
{
    nlohmann::json alarmJson;
    if (!alarmInfo.id.empty()) {
        alarmJson["id"] = alarmInfo.id;
    }
    if (!alarmInfo.alarmName.empty()) {
        alarmJson["name"] = alarmInfo.alarmName;
    }
    alarmJson["severity"] = alarmInfo.alarmSeverity;
    if (!alarmInfo.locationInfo.empty()) {
        alarmJson["locationInfo"] = alarmInfo.locationInfo;
    }
    if (!alarmInfo.cause.empty()) {
        alarmJson["cause"] = alarmInfo.cause;
    }
    if (alarmInfo.startsAt >= 0) {
        alarmJson["startsAt"] = alarmInfo.startsAt;
    }
    if (alarmInfo.endsAt >= 0) {
        alarmJson["endsAt"] = alarmInfo.endsAt;
    }
    if (alarmInfo.timeout > 0) {
        alarmJson["timeout"] = alarmInfo.timeout;
    }
    for (const auto &it : alarmInfo.customOptions) {
        std::visit([&alarmJson, &key(it.first)](auto& val) {
            alarmJson[key] = val;
        }, it.second);
    }
    return alarmJson;
}

Alarm::Alarm(std::unique_ptr<UInt64Gauge> &&gauge) : gauge_(std::move(gauge))
{
}

void Alarm::Set(const api::metrics::AlarmInfo &alarmInfo) noexcept
{
    auto alarmJson = ConvertEventModel(alarmInfo);
    observability::api::metrics::MetricLabels metricLabels;
    try {
        metricLabels.push_back(std::pair{::observability::metrics::ALARM_LABEL_KEY, alarmJson.dump()});
        gauge_->Set(1, metricLabels);
    } catch (std::exception &e) {
        METRICS_LOG_ERROR("dump alarmJson failed, error: {}", e.what());
    }
}
}