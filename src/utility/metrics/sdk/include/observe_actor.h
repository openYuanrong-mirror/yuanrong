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

#ifndef OBSERVABILITY_SDK_METRICS_OBSERVE_ACTOR_H
#define OBSERVABILITY_SDK_METRICS_OBSERVE_ACTOR_H

#include <unordered_set>
#include <map>
#include <memory>
#include "src/utility/timer_worker.h"
#include "metrics/exporters/exporter.h"
#include "metrics/sdk/metric_processor.h"

namespace observability::sdk::metrics {
namespace MetricsSdk = observability::sdk::metrics;
namespace MetricsExporter = observability::exporters::metrics;

using CollectFunc = std::function<void(int)>;

class ObserveActor {
public:
    ObserveActor() = default;
    ~ObserveActor();

    void RegisterTimer(const int interval);
    void RegisterCollectFunc(const CollectFunc &collectFunc)
    {
        collectFunc_ = collectFunc;
    };

    // for test
    [[maybe_unused]]std::unordered_set<int> GetCollectIntervals()
    {
        return collectIntervals_;
    }

    // for test
    [[maybe_unused]]std::map<int, std::shared_ptr<YR::utility::Timer>> GetCollectTimerMap()
    {
        return collectTimerMap_;
    }

private:
    std::unordered_set<int> collectIntervals_;
    std::map<int, std::shared_ptr<YR::utility::Timer>> collectTimerMap_;
    CollectFunc collectFunc_{ nullptr };

    void StartCollect(const int interval);
    void Collect(const int interval);
};
}
#endif // OBSERVABILITY_SDK_METRICS_OBSERVE_ACTOR_H
