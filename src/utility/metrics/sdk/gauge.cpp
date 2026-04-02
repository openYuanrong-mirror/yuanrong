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

#include "metrics/sdk/gauge.h"

#include "metrics/sdk/instruments.h"
#include "metrics/sdk/metric_recorder.h"

namespace observability::sdk::metrics {

UInt64Gauge::UInt64Gauge(const InstrumentDescriptor &instrumentDescriptor,
                         std::unique_ptr<SyncMetricRecorder> &&recorder)
    : SyncInstrument(instrumentDescriptor, std::move(recorder))
{
}

void UInt64Gauge::Set(const uint64_t val) noexcept
{
    if (!recorder_) {
        return;
    }
    recorder_->RecordUInt64(val, {}, std::chrono::system_clock::now());
}

void UInt64Gauge::Set(const uint64_t val, const PointLabels &labels) noexcept
{
    if (!recorder_) {
        return;
    }
    recorder_->RecordUInt64(val, labels, std::chrono::system_clock::now());
}

void UInt64Gauge::Set(const uint64_t val, const PointLabels &labels, const PointTimeStamp &timestamp) noexcept
{
    if (!recorder_) {
        return;
    }
    recorder_->RecordUInt64(val, labels, timestamp);
}

DoubleGauge::DoubleGauge(const InstrumentDescriptor &instrumentDescriptor,
                         std::unique_ptr<SyncMetricRecorder> &&recorder)
    : SyncInstrument(instrumentDescriptor, std::move(recorder))
{
}

void DoubleGauge::Set(const double val) noexcept
{
    if (!recorder_) {
        return;
    }
    recorder_->RecordDouble(val, {}, std::chrono::system_clock::now());
}

void DoubleGauge::Set(const double val, const PointLabels &labels) noexcept
{
    if (!recorder_) {
        return;
    }
    recorder_->RecordDouble(val, labels, std::chrono::system_clock::now());
}

void DoubleGauge::Set(const double val, const PointLabels &labels, const PointTimeStamp &timestamp) noexcept
{
    if (!recorder_) {
        return;
    }
    recorder_->RecordDouble(val, labels, timestamp);
}
}  // namespace observability::sdk::metrics