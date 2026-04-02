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

#ifndef OBSERVABILITY_API_METRICS_ALARM_DATA_H
#define OBSERVABILITY_API_METRICS_ALARM_DATA_H

#include <list>
#include <string>
#include <unordered_map>
#include <variant>
#include <vector>

#include "metrics/api/metric_data.h"

namespace observability::api::metrics {

enum class AlarmSeverity : int { OFF = 0, NOTICE = 1, INFO = 2, MINOR = 3, MAJOR = 4, CRITICAL = 5 };

struct AlarmInfo {
    std::string id;
    std::string alarmName;
    AlarmSeverity  alarmSeverity = AlarmSeverity::OFF;
    std::string locationInfo;
    std::string cause;
    long startsAt = -1L;
    long endsAt = -1L;
    long timeout = -1L;
    std::unordered_map<std::string, std::variant<int64_t, std::string, std::vector<std::string>>> customOptions;
};

}  // namespace observability::api::metrics

#endif
