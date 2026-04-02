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

#ifndef OBSERVABILITY_API_METRICS_NULL_H
#define OBSERVABILITY_API_METRICS_NULL_H

#include <cstdint>
#include <memory>

#include "metrics/api/gauge.h"
#include "metrics/api/counter.h"
#include "metrics/api/meter.h"
#include "metrics/api/meter_provider.h"
#include "metrics/api/metric_data.h"

namespace observability::api::metrics {

template <class T>
class NullGauge final : public Gauge<T> {
public:
    NullGauge(const std::string & /* name */, const std::string & /* description */,
              const std::string & /* unit */) noexcept
    {
    }
    ~NullGauge() override = default;

    void Set(const T) noexcept override
    {
    }

    void Set(const T, const MetricLabels &) noexcept override
    {
    }

    void Set(const T, const MetricLabels &, const SystemTimeStamp &) noexcept override
    {
    }
};

template <class T>
class NullCounter final : public Counter<T>  {
public:
    NullCounter(const std::string & /* name */, const std::string & /* description */,
                const std::string & /* unit */) noexcept
    {
    }
    ~NullCounter() override = default;

    void Set(const T) noexcept override
    {
    }

    void Set(const T, const MetricLabels &) noexcept override
    {
    }

    void Set(const T, const MetricLabels &, const SystemTimeStamp &) noexcept override
    {
    }

    void Reset() noexcept override
    {
    }

    void Increment(const T &) noexcept override
    {
    }

    T GetValue() noexcept override
    {
        return T();
    }

    const MetricLabels GetLabels() noexcept override
    {
        MetricLabels labels;
        return labels;
    }

    NullCounter &operator+=(const T &) noexcept override
    {
        return *this;
    }

    NullCounter &operator++() noexcept override
    {
        return *this;
    }
};

class NullObservableInstrument final : public ObservableInstrument {
public:
    NullObservableInstrument(const std::string & /* name */, const std::string & /* description */,
        const std::string & /* unit */) noexcept
    {
    }
    ~NullObservableInstrument() override = default;
};

class NullAlarm final : public Alarm {
public:
    NullAlarm(std::unique_ptr<Gauge<uint64_t>> /* &&gauge */) noexcept
    {
    }
    ~NullAlarm() override = default;

    void Set(const AlarmInfo &) noexcept override
    {
    }
};

class NullMeter final : public Meter {
public:
    ~NullMeter() override = default;
    std::unique_ptr<Gauge<uint64_t>> CreateUInt64Gauge(const std::string &name, const std::string &description = "",
                                                       const std::string &unit = "") noexcept override
    {
        return std::make_unique<NullGauge<uint64_t>>(name, description, unit);
    }

    std::unique_ptr<Gauge<double>> CreateDoubleGauge(const std::string &name, const std::string &description = "",
                                                     const std::string &unit = "") noexcept override
    {
        return std::make_unique<NullGauge<double>>(name, description, unit);
    }

    std::shared_ptr<ObservableInstrument> CreateUint64ObservableCounter(const std::string &name,
                                                                        const std::string &description,
                                                                        const std::string &unit,
                                                                        [[maybe_unused]]const uint32_t interval,
                                                                        [[maybe_unused]]const CallbackPtr &callback)
                                                                        noexcept override
    {
        return std::make_shared<NullObservableInstrument>(name, description, unit);
    }

    std::shared_ptr<ObservableInstrument> CreateDoubleObservableGauge(const std::string &name,
                                                                    const std::string &description,
                                                                    const std::string &unit,
                                                                    [[maybe_unused]]const uint32_t interval,
                                                                    [[maybe_unused]]const CallbackPtr &callback)
                                                                    noexcept override
    {
        return std::make_shared<NullObservableInstrument>(name, description, unit);
    }

    std::unique_ptr<Counter<uint64_t>> CreateUInt64Counter(const std::string &name,
                                                           const std::string &description = "",
                                                           const std::string &unit = "") noexcept override
    {
        return std::make_unique<NullCounter<uint64_t>>(name, description, unit);
    }

    std::unique_ptr<Counter<double>> CreateDoubleCounter(const std::string &name, const std::string &description = "",
                                                         const std::string &unit = "") noexcept override
    {
        return std::make_unique<NullCounter<double>>(name, description, unit);
    }

    std::unique_ptr<Alarm> CreateAlarm(const std::string &name, const std::string &description = "") noexcept override
    {
        auto gauge = std::make_unique<NullGauge<uint64_t>>(name, description, "");
        return std::make_unique<NullAlarm>(std::move(gauge));
    }
};

class NullMeterProvider final : public MeterProvider {
public:
    NullMeterProvider() noexcept : meter_{ std::make_shared<NullMeter>() }
    {
    }

    std::shared_ptr<Meter> GetMeter(const std::string &) noexcept override
    {
        return meter_;
    }

private:
    std::shared_ptr<Meter> meter_;
};

}  // namespace observability::api::metrics

#endif