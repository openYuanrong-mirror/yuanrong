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

#ifndef OBSERVABILITY_SDK_METRICS_ALARM_H
#define OBSERVABILITY_SDK_METRICS_ALARM_H

#include "metrics/api/alarm.h"
#include "metrics/api/alarm_data.h"
#include "metrics/sdk/gauge.h"

namespace observability::sdk::metrics {

class Alarm : public observability::api::metrics::Alarm {
public:
    explicit Alarm(std::unique_ptr<UInt64Gauge> &&gauge);
    ~Alarm() override = default;
    void Set(const api::metrics::AlarmInfo &alarmInfo) noexcept override;

private:
    std::unique_ptr<UInt64Gauge> gauge_;
};
}  // namespace observability::api::metrics

#endif
