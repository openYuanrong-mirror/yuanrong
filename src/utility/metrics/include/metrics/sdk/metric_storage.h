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

#ifndef OBSERVABILITY_SDK_METRICS_METRIC_STORAGE_H
#define OBSERVABILITY_SDK_METRICS_METRIC_STORAGE_H

#include "metrics/sdk/instruments.h"
#include "metrics/sdk/metric_data.h"
#include "metrics/sdk/metric_recorder.h"

namespace observability::sdk::metrics {

class PusherHandle;
struct MetricData;

class ActivesStorage {
public:
    virtual ~ActivesStorage() = default;
    virtual void Push(const std::vector<std::shared_ptr<PusherHandle>> &pushers, MetricData metricData) noexcept;
};

class ActivesMetricsStorage : public ActivesStorage, public SyncMetricRecorder {
public:
    ActivesMetricsStorage(const InstrumentDescriptor &instrumentDescriptor,
                          const std::vector<std::shared_ptr<PusherHandle>> &pushers);
    ~ActivesMetricsStorage() override = default;

    void RecordUInt64(const uint64_t value, const PointLabels &labels,
                      const PointTimeStamp &timestamp) noexcept override;

    void RecordInt64(const int64_t value, const PointLabels &labels, const PointTimeStamp &timestamp) noexcept override;

    void RecordDouble(const double value, const PointLabels &labels, const PointTimeStamp &timestamp) noexcept override;

private:
    InstrumentDescriptor instrumentDescriptor_;
    std::vector<std::shared_ptr<PusherHandle>> pushers_;
};
}  // namespace observability::sdk::metrics
#endif
