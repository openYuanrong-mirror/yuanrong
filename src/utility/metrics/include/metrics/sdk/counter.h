/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2024. All rights reserved.
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

#ifndef OBSERVABILITY_SDK_METRICS_COUNTER_H
#define OBSERVABILITY_SDK_METRICS_COUNTER_H

#include <memory>
#include <atomic>
#include <mutex>

#include "metrics/api/counter.h"
#include "metrics/sdk/instruments.h"
#include "metrics/sdk/metric_data.h"

namespace observability::sdk::metrics {

class UInt64Counter : public SyncInstrument, public observability::api::metrics::Counter<uint64_t> {
public:
    UInt64Counter(const InstrumentDescriptor &instrumentDescriptor, std::unique_ptr<SyncMetricRecorder> &&recorder);
    ~UInt64Counter() override = default;
    void Set(const uint64_t val) noexcept override;
    void Set(const uint64_t val, const PointLabels &labels) noexcept override;
    void Set(const uint64_t val, const PointLabels &labels, const PointTimeStamp &timestamp) noexcept override;
    void Reset() noexcept override;
    void Increment(const uint64_t &val) noexcept override;
    uint64_t GetValue() noexcept override;
    const PointLabels GetLabels() noexcept override;

    UInt64Counter &operator+=(const uint64_t &val) noexcept override
    {
        Increment(val);
        return *this;
    }
    UInt64Counter &operator++() noexcept override
    {
        const uint64_t val = 1;
        Increment(val);
        return *this;
    }

private:
    std::atomic<uint64_t> value_{ 0 };
    std::mutex mutex_;
    PointLabels labels_;
};

class DoubleCounter : public SyncInstrument, public observability::api::metrics::Counter<double> {
public:
    DoubleCounter(const InstrumentDescriptor &instrumentDescriptor, std::unique_ptr<SyncMetricRecorder> &&recorder);
    ~DoubleCounter() override = default;
    void Set(const double val) noexcept override;
    void Set(const double val, const PointLabels &labels) noexcept override;
    void Set(const double val, const PointLabels &labels, const PointTimeStamp &timestamp) noexcept override;
    void Reset() noexcept override;
    void Increment(const double &val) noexcept override;
    double GetValue() noexcept override;
    const PointLabels GetLabels() noexcept override;

    DoubleCounter &operator+=(const double &val) noexcept override
    {
        Increment(val);
        return *this;
    }

    DoubleCounter &operator++() noexcept override
    {
        const double val = 1.0;
        Increment(val);
        return *this;
    }

private:
    std::atomic<double> value_{ 0.0 };
    std::mutex mutex_;
    PointLabels labels_;
};

} // namespace observability::sdk::metrics

#endif  // OBSERVABILITY_SDK_METRICS_COUNTER_H
