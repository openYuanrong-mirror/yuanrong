/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2024-2024. All rights reserved.
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

#include "metrics/sdk/counter.h"

#include "src/utility/metrics/common/include/atomic_calc.h"
#include "metrics/sdk/instruments.h"
#include "metrics/sdk/metric_recorder.h"

namespace observability::sdk::metrics {

UInt64Counter::UInt64Counter(const InstrumentDescriptor &instrumentDescriptor,
                             std::unique_ptr<SyncMetricRecorder> &&recorder)
    : SyncInstrument(instrumentDescriptor, std::move(recorder))
{
}

void UInt64Counter::Set(const uint64_t val) noexcept
{
    if (!recorder_) {
        return;
    }
    std::lock_guard<std::mutex> lock{ mutex_ };
    value_ = val;
    recorder_->RecordUInt64(value_, {}, std::chrono::system_clock::now());
}

void UInt64Counter::Set(const uint64_t val, const PointLabels &labels) noexcept
{
    if (!recorder_) {
        return;
    }
    std::lock_guard<std::mutex> lock{ mutex_ };
    value_ = val;
    labels_.assign(labels.begin(), labels.end());
    recorder_->RecordUInt64(value_, labels, std::chrono::system_clock::now());
}

void UInt64Counter::Set(const uint64_t val, const PointLabels &labels, const PointTimeStamp &timestamp) noexcept
{
    if (!recorder_) {
        return;
    }
    std::lock_guard<std::mutex> lock{ mutex_ };
    value_ = val;
    labels_.assign(labels.begin(), labels.end());
    recorder_->RecordUInt64(value_, labels, timestamp);
}

void UInt64Counter::Reset() noexcept
{
    if (!recorder_) {
        return;
    }
    std::lock_guard<std::mutex> lock{ mutex_ };
    value_ = 0;
    recorder_->RecordUInt64(value_, labels_, std::chrono::system_clock::now());
}

void UInt64Counter::Increment(const uint64_t &val) noexcept
{
    if (!recorder_) {
        return;
    }
    std::lock_guard<std::mutex> lock{ mutex_ };
    value_ += val;
    recorder_->RecordUInt64(value_, labels_, std::chrono::system_clock::now());
}

uint64_t UInt64Counter::GetValue() noexcept
{
    std::lock_guard<std::mutex> lock{ mutex_ };
    return value_;
}

const PointLabels UInt64Counter::GetLabels() noexcept
{
    return labels_;
}

DoubleCounter::DoubleCounter(const InstrumentDescriptor &instrumentDescriptor,
                             std::unique_ptr<SyncMetricRecorder> &&recorder)
    : SyncInstrument(instrumentDescriptor, std::move(recorder))
{
}

void DoubleCounter::Set(const double val) noexcept
{
    if (!recorder_) {
        return;
    }
    std::lock_guard<std::mutex> lock{ mutex_ };
    if (val < 0) {
        return;
    }
    value_ = val;
    recorder_->RecordDouble(value_, {}, std::chrono::system_clock::now());
}

void DoubleCounter::Set(const double val, const PointLabels &labels) noexcept
{
    if (!recorder_) {
        return;
    }
    std::lock_guard<std::mutex> lock{ mutex_ };
    if (val < 0) {
        return;
    }
    value_ = val;
    labels_.assign(labels.begin(), labels.end());
    recorder_->RecordDouble(value_, labels, std::chrono::system_clock::now());
}

void DoubleCounter::Set(const double val, const PointLabels &labels, const PointTimeStamp &timestamp) noexcept
{
    if (!recorder_) {
        return;
    }
    std::lock_guard<std::mutex> lock{ mutex_ };
    if (val < 0) {
        return;
    }
    value_ = val;
    labels_.assign(labels.begin(), labels.end());
    recorder_->RecordDouble(value_, labels, timestamp);
}

void DoubleCounter::Reset() noexcept
{
    if (!recorder_) {
        return;
    }
    std::lock_guard<std::mutex> lock{ mutex_ };
    value_ = 0.0;
    recorder_->RecordDouble(value_, labels_, std::chrono::system_clock::now());
}

void DoubleCounter::Increment(const double &val) noexcept
{
    if (!recorder_) {
        return;
    }
    std::lock_guard<std::mutex> lock{ mutex_ };
    if (val < 0.0) {
        return;
    }
    observability::metrics::AtomicAdd(value_, val);
    recorder_->RecordDouble(value_, labels_, std::chrono::system_clock::now());
}

double DoubleCounter::GetValue() noexcept
{
    std::lock_guard<std::mutex> lock{ mutex_ };
    return value_;
}

const PointLabels DoubleCounter::GetLabels() noexcept
{
    return labels_;
}

}  // namespace observability::sdk::metrics
