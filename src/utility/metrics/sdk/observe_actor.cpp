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

#include "src/utility/metrics/sdk/include/observe_actor.h"

#include "src/utility/metrics/common/include/metric_logger.h"

namespace observability::sdk::metrics {

const uint16_t SEC2MS = 1000;

ObserveActor::~ObserveActor()
{
    for (auto timerInfo : collectTimerMap_) {
        auto timer = timerInfo.second;
        if (timer) {
            YR::utility::CancelGlobalTimer(timer);
        }
    }
    collectTimerMap_.clear();
    collectIntervals_.clear();
}

void ObserveActor::RegisterTimer(const int interval)
{
    if (interval <= 0) {
        METRICS_LOG_ERROR("Invalid interval {}", interval);
        return;
    }
    if (auto it = collectIntervals_.find(interval); it == collectIntervals_.end()) {
        METRICS_LOG_DEBUG("Register observable instrument timer {}", interval);
        collectIntervals_.insert(interval);
        StartCollect(interval);  // Start collection immediately
    }
}

void ObserveActor::StartCollect(const int interval)
{
    METRICS_LOG_DEBUG("Start to collect {} observable instrument", interval);

    // Collect immediately
    Collect(interval);

    // Schedule next collection
    collectTimerMap_[interval] = YR::utility::ExecuteByGlobalTimer(
        [this, interval]() {
            if (collectIntervals_.count(interval) > 0) {
                StartCollect(interval);  // Reschedule
            }
        },
        interval * SEC2MS,  // Convert to milliseconds
        -1  // Execute indefinitely
    );
}

void ObserveActor::Collect(const int interval)
{
    if (collectFunc_) {
        collectFunc_(interval);
    }
}
}
