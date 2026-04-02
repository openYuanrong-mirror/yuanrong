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

#ifndef OBSERVABILITY_SDK_METRICS_GAUGE_H
#define OBSERVABILITY_SDK_METRICS_GAUGE_H

#include <memory>

#include "metrics/api/gauge.h"
#include "metrics/sdk/instruments.h"
#include "metrics/sdk/metric_data.h"

namespace observability::sdk::metrics {

class UInt64Gauge : public SyncInstrument, public observability::api::metrics::Gauge<uint64_t> {
public:
    UInt64Gauge(const InstrumentDescriptor &instrumentDescriptor, std::unique_ptr<SyncMetricRecorder> &&recorder);
    ~UInt64Gauge() override = default;
    void Set(const uint64_t val) noexcept override;
    void Set(const uint64_t val, const PointLabels &labels) noexcept override;
    void Set(const uint64_t val, const PointLabels &labels, const PointTimeStamp &timestamp) noexcept override;
};

class DoubleGauge : public SyncInstrument, public observability::api::metrics::Gauge<double> {
public:
    DoubleGauge(const InstrumentDescriptor &instrumentDescriptor, std::unique_ptr<SyncMetricRecorder> &&recorder);
    ~DoubleGauge() override = default;
    void Set(const double val) noexcept override;
    void Set(const double val, const PointLabels &labels) noexcept override;
    void Set(const double val, const PointLabels &labels, const PointTimeStamp &timestamp) noexcept override;
};

}  // namespace observability::sdk::metrics

#endif