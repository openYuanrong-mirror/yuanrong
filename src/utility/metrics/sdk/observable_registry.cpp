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

#include "metrics/api/observe_result_t.h"
#include "metrics/sdk/metric_pusher.h"
#include "src/utility/metrics/common/include/metric_logger.h"

#include "src/utility/metrics/sdk/include/observe_actor.h"
#include "src/utility/metrics/sdk/include/observable_registry.h"

namespace observability::sdk::metrics {
void ObservableRegistry::AddObservableInstrument(api::metrics::CallbackPtr callbackPtr,
                                                 const InstrumentDescriptor &instrument, const int interval)
{
    METRICS_LOG_DEBUG("Add observable instrument: {} timer: {}", instrument.name, interval);
    AsyncCallbackRecord callbackRecord;
    callbackRecord.cb = callbackPtr;
    callbackRecord.instrument = instrument;

    std::lock_guard<std::mutex> lock(callbackMapMutex_);
    auto it = callbackIntervalMap_.find(interval);
    if (it != callbackIntervalMap_.end()) {
        it->second.push_back(callbackRecord);
    } else {
        std::vector<AsyncCallbackRecord> asyncCallbackRecords;
        asyncCallbackRecords.push_back(std::move(callbackRecord));
        callbackIntervalMap_[interval] = std::move(asyncCallbackRecords);
    }
    std::lock_guard<std::mutex> collectIntervalLock(mutex_);
    auto collectIntervalIt = collectIntervalMap_.find(interval);
    if (collectIntervalIt != collectIntervalMap_.end()) {
        collectIntervalIt->second.push_back(instrument);
    } else {
        std::vector<InstrumentDescriptor> instrumentDescriptorList;
        instrumentDescriptorList.push_back(instrument);
        collectIntervalMap_[interval] = instrumentDescriptorList;
    }
}

void ObservableRegistry::DoPush(std::vector<MetricData> metricDataVec)
{
    for (auto &metricData : metricDataVec) {
        for (auto &p : pushers_) {
            if (p == nullptr) {
                continue;
            }
            p->Push(metricData);
        }
    }
}

void ObservableRegistry::Observe(const int interval)
{
    std::lock_guard<std::mutex> lock(callbackMapMutex_);
    auto it = callbackIntervalMap_.find(interval);
    if (it == callbackIntervalMap_.end()) {
        return;
    }
    METRICS_LOG_DEBUG("callbackRecord size {}", it->second.size());
    for (const auto &callbackRecord : it->second) {
        auto instrument = callbackRecord.instrument;
        auto valueType = instrument.valueType;
        if (valueType == InstrumentValueType::UINT64) {
            auto observeResult = std::make_shared<api::metrics::ObserveResultT<uint64_t>>();
            auto callback = callbackRecord.cb;
            callback(observeResult);
            Push(observeResult->Value(), callbackRecord.instrument);
        } else if (valueType == InstrumentValueType::INT64) {
            auto observeResult = std::make_shared<api::metrics::ObserveResultT<int64_t>>();
            auto callback = callbackRecord.cb;
            callback(observeResult);
            Push(observeResult->Value(), callbackRecord.instrument);
        } else if (valueType == InstrumentValueType::DOUBLE) {
            auto observeResult = std::make_shared<api::metrics::ObserveResultT<double>>();
            auto callback = callbackRecord.cb;
            callback(observeResult);
            Push(observeResult->Value(), callbackRecord.instrument);
        } else {
            METRICS_LOG_WARN("Unsupported value type {}", static_cast<int>(valueType));
        }
    }
}

template <typename T>
void ObservableRegistry::Push(std::vector<std::pair<api::metrics::MetricLabels, T>> observeRes,
                              const InstrumentDescriptor &instrumentDescriptor)
{
    if (observeRes.size() == 0) {
        METRICS_LOG_INFO("Observable res is empty");
        return;
    }
    METRICS_LOG_DEBUG("{} observeRes size: {}", instrumentDescriptor.name, observeRes.size());
    std::vector<MetricData> metricDataVec;
    for (auto it : observeRes) {
        MetricData metricData;
        metricData.instrumentDescriptor = instrumentDescriptor;
        metricData.collectionTs = std::chrono::system_clock::now();
        PointData pointData;
        pointData.labels = it.first;
        pointData.value = it.second;
        metricData.pointData.push_back(pointData);
        metricDataVec.push_back(metricData);
    }
    METRICS_LOG_INFO("metricDataVec size {}", metricDataVec.size());
    DoPush(metricDataVec);
}
}
