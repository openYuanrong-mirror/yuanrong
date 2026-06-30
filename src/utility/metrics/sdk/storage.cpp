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

#include "src/utility/metrics/api/include/gauge.h"
#include "src/utility/metrics/common/include/transfer.h"
#include "src/utility/metrics/sdk/include/storage.h"

namespace observability {
namespace metrics {

void Storage::AddMetricAsync(CallbackPtr callbackPtr, const MetricValue &state,
                             const std::shared_ptr<BasicMetric> &instrument,
                             const int interval)
{
    std::unique_ptr<AsyncCallbackRecord> callbackRecord = std::make_unique<AsyncCallbackRecord>();
    callbackRecord->cb = std::make_shared<CallbackPtr>(callbackPtr);
    callbackRecord->instrument = instrument;
    callbackRecord->state = state;

    std::lock_guard<std::mutex> lock(callbackMapMutex_);
    auto it = callbackIntervalMap_.find(interval);
    if (it != callbackIntervalMap_.end()) {
        it->second.push_back(std::move(callbackRecord));
    } else {
        std::vector<std::unique_ptr<AsyncCallbackRecord>> asyncCallbackRecords;
        asyncCallbackRecords.push_back(std::move(callbackRecord));
        callbackIntervalMap_[interval] = std::move(asyncCallbackRecords);
    }
    AddMetric(instrument, interval);
}

void Storage::AddMetric(const std::shared_ptr<BasicMetric> &instrument, const int interval)
{
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = collectIntervalMap_.find(interval);
    if (it != collectIntervalMap_.end()) {
        it->second.push_back(instrument);
    } else {
        std::vector<std::shared_ptr<BasicMetric>> metricList;
        metricList.push_back(instrument);
        collectIntervalMap_[interval] = metricList;
    }
}

template <typename T>
void Storage::SetValueForInstrument(const std::shared_ptr<BasicMetric> &instrument, const T &value) const
{
    MetricType metricType = instrument->GetMetricType();
    switch (metricType) {
        case MetricType::GAUGE: {
            auto gauge = std::static_pointer_cast<Gauge<T>>(instrument);
            gauge->Set(value);
            break;
        }
        case MetricType::COUNTER:
        case MetricType::SUMMARY:
        case MetricType::HISTOGRAM:
        default:
            break;
    }
}

void Storage::Observe(const int interval)
{
    std::lock_guard<std::mutex> lock(callbackMapMutex_);
    auto it = callbackIntervalMap_.find(interval);
    if (it == callbackIntervalMap_.end()) {
        return;
    }
    for (const auto &callbackRecord : it->second) {
        auto instrument = callbackRecord->instrument;
        auto valueType = instrument->GetValueType();
        if (valueType == ValueType::INT) {
            auto observeResult = std::make_shared<ObserverResultT<int64_t>>();
            auto callback = *(callbackRecord->cb);
            callback(observeResult, callbackRecord->state);
            SetValueForInstrument(instrument, observeResult->Value());
        } else if (valueType == ValueType::UINT) {
            auto observeResult = std::make_shared<ObserverResultT<uint64_t>>();
            auto callback = *(callbackRecord->cb);
            callback(observeResult, callbackRecord->state);
            SetValueForInstrument(instrument, observeResult->Value());
        } else {
            auto observeResult = std::make_shared<ObserverResultT<double>>();
            auto callback = *(callbackRecord->cb);
            callback(observeResult, callbackRecord->state);
            SetValueForInstrument(instrument, observeResult->Value());
        }
    }
}

std::vector<MetricsData> Storage::Collect(const std::chrono::system_clock::time_point& collectTime,
                                          const int interval)
{
    Observe(interval);

    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<MetricsData> metricDataList;

    auto it = collectIntervalMap_.find(interval);
    if (it != collectIntervalMap_.end()) {
        auto instruments = it->second;
        for (const auto &instrument : instruments) {
            auto timestamp =
                instrument->GetTimestamp().time_since_epoch().count() == 0 ? collectTime : instrument->GetTimestamp();
            MetricsData metricData = {
                .labels = instrument->GetLabels(),
                .name = instrument->GetName(),
                .description = instrument->GetDescription(),
                .unit = instrument->GetUnit(),
                .metricType = GetMetricTypeStr(instrument->GetMetricType()),
                .collectTimeStamp = timestamp,
                .metricValue = GetInstrumentValue(instrument)
            };
            metricDataList.push_back(metricData);
        }
    }
    if (interval == 0) {
        (void)collectIntervalMap_.erase(interval);
        std::lock_guard<std::mutex> callbackLock(callbackMapMutex_);
        (void)callbackIntervalMap_.erase(interval);
    }
    return metricDataList;
}

}  // namespace metrics
}  // namespace observability