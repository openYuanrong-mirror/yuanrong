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

#ifndef OBSERVABILITY_SDK_METRICS_OBSERVABLE_REGISTRY_H
#define OBSERVABILITY_SDK_METRICS_OBSERVABLE_REGISTRY_H

#include <map>

#include "metrics/api/meter.h"
#include "metrics/sdk/metric_pusher.h"
#include "src/utility/metrics/sdk/include/observe_actor.h"

namespace observability::sdk::metrics {

struct AsyncCallbackRecord {
    api::metrics::CallbackPtr cb;
    InstrumentDescriptor instrument;
    PointValue state;
};

class ObservableRegistry {
public:

    explicit ObservableRegistry(std::vector<std::shared_ptr<PusherHandle>> pushers): pushers_(pushers)
    {
        observeActor_ = std::make_shared<ObserveActor>();
        observeActor_->RegisterCollectFunc(
            std::bind(&ObservableRegistry::Observe, this, std::placeholders::_1));
    }

    ~ObservableRegistry()
    {
        // ObserveActor destructor will handle cleanup
    }

    void AddObservableInstrument(api::metrics::CallbackPtr callbackPtr, const InstrumentDescriptor &instrument,
                                 const int interval);

    void Observe(const int interval);

    // for test
    [[maybe_unused]]std::map<int, std::vector<AsyncCallbackRecord>> GetCallbackIntervalMap()
    {
        return callbackIntervalMap_;
    }

    // for test
    [[maybe_unused]]std::map<int, std::vector<InstrumentDescriptor>> GetCollectIntervalMap()
    {
        return collectIntervalMap_;
    }

private:
    void DoPush(std::vector<MetricData> metricDataVec);

    template <typename T>
    void Push(std::vector<std::pair<api::metrics::MetricLabels, T>> observeRes,
              const InstrumentDescriptor &instrumentDescriptor);

    std::map<int, std::vector<AsyncCallbackRecord>> callbackIntervalMap_;
    std::map<int, std::vector<InstrumentDescriptor>> collectIntervalMap_;
    std::mutex callbackMapMutex_;
    std::mutex mutex_;
    std::vector<std::shared_ptr<PusherHandle>> pushers_;
    std::shared_ptr<ObserveActor> observeActor_;
};
}

#endif // OBSERVABILITY_SDK_METRICS_OBSERVABLE_REGISTRY_H
