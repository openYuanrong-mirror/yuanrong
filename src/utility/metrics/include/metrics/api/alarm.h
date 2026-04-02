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

#ifndef OBSERVABILITY_API_METRICS_ALARM_H
#define OBSERVABILITY_API_METRICS_ALARM_H

#include "metrics/api/alarm_data.h"

namespace observability::api::metrics {

class Alarm {
public:
    virtual ~Alarm() = default;

    virtual void Set(const AlarmInfo &alarmInfo) noexcept = 0;
};

}  // namespace observability::api::metrics

#endif
