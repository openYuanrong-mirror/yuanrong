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

#include "metrics/sdk/metric_storage.h"

#include "metrics/sdk/instruments.h"
#include "metrics/sdk/metric_data.h"
#include "metrics/sdk/metric_pusher.h"

namespace observability::sdk::metrics {

template <typename T>
MetricData BuildMetricsData(const InstrumentDescriptor &instrumentDescriptor, const T val, const PointLabels &labels,
                            const PointTimeStamp &collectionTs)
{
    MetricData data;
    data.instrumentDescriptor = instrumentDescriptor;
    data.collectionTs = collectionTs;
    PointData pointData;
    pointData.labels = labels;
    pointData.value = val;
    data.pointData.push_back(pointData);
    return data;
}

void ActivesStorage::Push(const std::vector<std::shared_ptr<PusherHandle>> &pushers, MetricData metricData) noexcept
{
    for (auto &p : pushers) {
        if (p == nullptr) {
            continue;
        }
        p->Push(metricData);
    }
}

ActivesMetricsStorage::ActivesMetricsStorage(const InstrumentDescriptor &instrumentDescriptor,
                                             const std::vector<std::shared_ptr<PusherHandle>> &pushers)
    : instrumentDescriptor_(instrumentDescriptor), pushers_(pushers)
{
}

void ActivesMetricsStorage::RecordUInt64(const uint64_t value, const PointLabels &labels,
                                         const PointTimeStamp &timestamp) noexcept
{
    if (instrumentDescriptor_.valueType != InstrumentValueType::UINT64) {
        return;
    }
    Push(pushers_, BuildMetricsData(instrumentDescriptor_, value, labels, timestamp));
}

void ActivesMetricsStorage::RecordInt64(const int64_t value, const PointLabels &labels,
                                        const PointTimeStamp &timestamp) noexcept
{
    if (instrumentDescriptor_.valueType != InstrumentValueType::INT64) {
        return;
    }
    Push(pushers_, BuildMetricsData(instrumentDescriptor_, value, labels, timestamp));
}

void ActivesMetricsStorage::RecordDouble(const double value, const PointLabels &labels,
                                         const PointTimeStamp &timestamp) noexcept
{
    if (instrumentDescriptor_.valueType != InstrumentValueType::DOUBLE) {
        return;
    }
    Push(pushers_, BuildMetricsData(instrumentDescriptor_, value, labels, timestamp));
}

}  // namespace observability::sdk::metrics