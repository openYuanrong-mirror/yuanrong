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

#ifndef OBSERVABILITY_SDK_METRICS_METER_H
#define OBSERVABILITY_SDK_METRICS_METER_H

#include <memory>
#include <mutex>
#include <unordered_map>

#include "metrics/api/meter.h"
#include "metrics/sdk/instruments.h"
#include "metrics/sdk/metric_storage.h"

namespace observability::sdk::metrics {
class MeterContext;
class ObservableRegistry;

class Meter final : public observability::api::metrics::Meter {
public:
    explicit Meter(const std::weak_ptr<MeterContext> &context, const std::string &name = "") noexcept;
    std::string GetName() const noexcept;

    std::unique_ptr<observability::api::metrics::Gauge<uint64_t>> CreateUInt64Gauge(
        const std::string &name, const std::string &description = "", const std::string &unit = "") noexcept override;
    std::unique_ptr<observability::api::metrics::Gauge<double>> CreateDoubleGauge(
        const std::string &name, const std::string &description = "", const std::string &unit = "") noexcept override;
    std::shared_ptr<api::metrics::ObservableInstrument> CreateUint64ObservableCounter(const std::string &name,
        const std::string &description, const std::string &unit, const uint32_t interval,
        const api::metrics::CallbackPtr &callback) noexcept override;
    std::shared_ptr<api::metrics::ObservableInstrument> CreateDoubleObservableGauge(const std::string &name,
        const std::string &description, const std::string &unit, const uint32_t interval,
        const api::metrics::CallbackPtr &callback) noexcept override;

    std::unique_ptr<observability::api::metrics::Counter<uint64_t>> CreateUInt64Counter(
        const std::string &name, const std::string &description = "", const std::string &unit = "") noexcept override;
    std::unique_ptr<observability::api::metrics::Counter<double>> CreateDoubleCounter(
        const std::string &name, const std::string &description = "", const std::string &unit = "") noexcept override;
    std::unique_ptr<observability::api::metrics::Alarm> CreateAlarm(
        const std::string &name, const std::string &description = "") noexcept override;

private:
    std::unique_ptr<SyncMetricRecorder> RegisterSyncMetricRecorder(const InstrumentDescriptor &instrumentDescriptor);
    std::weak_ptr<MeterContext> meterContext_;
    std::string name_;
    std::unordered_map<std::string, std::shared_ptr<ActivesStorage>> activesStorage_;
    std::mutex recorderLock_;
    std::mutex asyncStorageLock_;
    std::shared_ptr<ObservableRegistry> observableRegistry_;
};
}  // namespace observability::sdk::metrics

#endif