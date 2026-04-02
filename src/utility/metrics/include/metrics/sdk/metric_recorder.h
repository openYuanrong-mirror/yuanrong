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

#ifndef OBSERVABILITY_SDK_METRICS_METRIC_RECORDER_H
#define OBSERVABILITY_SDK_METRICS_METRIC_RECORDER_H

#include <list>
#include <memory>
#include <unordered_map>
#include <vector>

#include "metrics/sdk/metric_data.h"

namespace observability::sdk::metrics {
class SyncMetricRecorder {
public:
    virtual ~SyncMetricRecorder() = default;

    virtual void RecordUInt64(const uint64_t value, const PointLabels &labels,
                              const PointTimeStamp &timestamp) noexcept = 0;

    virtual void RecordInt64(const int64_t value, const PointLabels &labels,
                             const PointTimeStamp &timestamp) noexcept = 0;

    virtual void RecordDouble(const double value, const PointLabels &labels,
                              const PointTimeStamp &timestamp) noexcept = 0;
};

class SyncMultiMetricRecorder : public SyncMetricRecorder {
public:
    SyncMultiMetricRecorder() = default;
    ~SyncMultiMetricRecorder() override = default;
    void AddRecorder(const std::shared_ptr<SyncMetricRecorder> &recorder)
    {
        recorders_.push_back(recorder);
    }

    void RecordUInt64(const uint64_t value, const PointLabels &labels,
                      const PointTimeStamp &timestamp) noexcept override
    {
        for (auto &r : recorders_) {
            r->RecordUInt64(value, labels, timestamp);
        }
    }

    void RecordInt64(const int64_t value, const PointLabels &labels, const PointTimeStamp &timestamp) noexcept override
    {
        for (auto &r : recorders_) {
            r->RecordInt64(value, labels, timestamp);
        }
    }

    void RecordDouble(const double value, const PointLabels &labels, const PointTimeStamp &timestamp) noexcept override
    {
        for (auto &r : recorders_) {
            r->RecordDouble(value, labels, timestamp);
        }
    }

private:
    std::vector<std::shared_ptr<SyncMetricRecorder>> recorders_;
};

}  // namespace observability::sdk::metrics
#endif
