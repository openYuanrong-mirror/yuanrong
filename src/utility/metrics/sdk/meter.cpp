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
#include "metrics/sdk/meter.h"

#include "metrics/sdk/counter.h"
#include "metrics/sdk/gauge.h"
#include "metrics/sdk/instruments.h"
#include "metrics/sdk/meter_context.h"
#include "metrics/sdk/metric_storage.h"
#include "metrics/sdk/alarm.h"
#include "src/utility/metrics/sdk/include/observable_registry.h"

namespace MetricsApi = observability::api::metrics;

namespace observability::sdk::metrics {

Meter::Meter(const std::weak_ptr<MeterContext> &context, const std::string &name) noexcept
    : meterContext_(context), name_(name)
{
    auto ctx = meterContext_.lock();
    auto pushers = ctx->GetPushers();
    observableRegistry_ = std::make_unique<ObservableRegistry>(pushers);
}

std::string Meter::GetName() const noexcept
{
    return name_;
}

std::unique_ptr<MetricsApi::Gauge<uint64_t>> Meter::CreateUInt64Gauge(const std::string &name,
                                                                      const std::string &description,
                                                                      const std::string &unit) noexcept
{
    InstrumentDescriptor instrumentDescriptor = { name, description, unit, InstrumentType::GAUGE,
                                                  InstrumentValueType::UINT64 };
    auto recorder = RegisterSyncMetricRecorder(instrumentDescriptor);
    return std::make_unique<UInt64Gauge>(instrumentDescriptor, std::move(recorder));
}

std::unique_ptr<MetricsApi::Gauge<double>> Meter::CreateDoubleGauge(const std::string &name,
                                                                    const std::string &description,
                                                                    const std::string &unit) noexcept
{
    InstrumentDescriptor instrumentDescriptor = { name, description, unit, InstrumentType::GAUGE,
                                                  InstrumentValueType::DOUBLE };
    auto recorder = RegisterSyncMetricRecorder(instrumentDescriptor);

    return std::make_unique<DoubleGauge>(instrumentDescriptor, std::move(recorder));
}

std::shared_ptr<MetricsApi::ObservableInstrument> Meter::CreateUint64ObservableCounter(const std::string &name,
    const std::string &description, const std::string &unit, const uint32_t interval,
    const MetricsApi::CallbackPtr &callback) noexcept
{
    InstrumentDescriptor instrumentDescriptor = { name, description, unit, InstrumentType::COUNTER,
                                                  InstrumentValueType::UINT64 };

    if (observableRegistry_ == nullptr) {
        return nullptr;
    }
    observableRegistry_->AddObservableInstrument(callback, instrumentDescriptor, interval);
    return std::unique_ptr<api::metrics::ObservableInstrument>{
        new sdk::metrics::ObservableInstrument(instrumentDescriptor)};
}

std::shared_ptr<api::metrics::ObservableInstrument> Meter::CreateDoubleObservableGauge(const std::string &name,
    const std::string &description, const std::string &unit, const uint32_t interval,
    const api::metrics::CallbackPtr &callback) noexcept
{
    InstrumentDescriptor instrumentDescriptor = { name, description, unit, InstrumentType::GAUGE,
                                                  InstrumentValueType::DOUBLE };

    if (observableRegistry_ == nullptr) {
        return nullptr;
    }
    observableRegistry_->AddObservableInstrument(callback, instrumentDescriptor, interval);
    return std::unique_ptr<api::metrics::ObservableInstrument>{
        new sdk::metrics::ObservableInstrument(instrumentDescriptor)};
}

std::unique_ptr<SyncMetricRecorder> Meter::RegisterSyncMetricRecorder(const InstrumentDescriptor &instrumentDescriptor)
{
    std::lock_guard<std::mutex> guard(recorderLock_);
    auto context = meterContext_.lock();
    if (!context) {
        return nullptr;
    }
    std::unique_ptr<SyncMultiMetricRecorder> recorders = std::make_unique<SyncMultiMetricRecorder>();
    auto pushers = context->GetPushers();
    if (pushers.size() > 0) {
        auto recorder = std::make_shared<ActivesMetricsStorage>(instrumentDescriptor, pushers);
        activesStorage_[instrumentDescriptor.name] = recorder;
        recorders->AddRecorder(recorder);
    }

    return recorders;
}

std::unique_ptr<MetricsApi::Counter<uint64_t>> Meter::CreateUInt64Counter(const std::string &name,
                                                                          const std::string &description,
                                                                          const std::string &unit) noexcept
{
    InstrumentDescriptor instrumentDescriptor = { name, description, unit, InstrumentType::COUNTER,
                                                  InstrumentValueType::UINT64 };
    auto recorder = RegisterSyncMetricRecorder(instrumentDescriptor);
    return std::make_unique<UInt64Counter>(instrumentDescriptor, std::move(recorder));
}

std::unique_ptr<MetricsApi::Counter<double>> Meter::CreateDoubleCounter(const std::string &name,
                                                                        const std::string &description,
                                                                        const std::string &unit) noexcept
{
    InstrumentDescriptor instrumentDescriptor = { name, description, unit, InstrumentType::COUNTER,
                                                  InstrumentValueType::DOUBLE };
    auto recorder = RegisterSyncMetricRecorder(instrumentDescriptor);
    return std::make_unique<DoubleCounter>(instrumentDescriptor, std::move(recorder));
}

std::unique_ptr<MetricsApi::Alarm> Meter::CreateAlarm(const std::string &name, const std::string &description) noexcept
{
    InstrumentDescriptor instrumentDescriptor = { name, description, "", InstrumentType::GAUGE,
                                                  InstrumentValueType::UINT64 };
    auto recorder = RegisterSyncMetricRecorder(instrumentDescriptor);
    auto gauge = std::make_unique<UInt64Gauge>(instrumentDescriptor, std::move(recorder));
    return std::make_unique<MetricsSdk::Alarm>(std::move(gauge));
}

}  // namespace observability::sdk::metrics