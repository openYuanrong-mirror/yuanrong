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

#ifndef OBSERVABILITY_API_METRICS_METER_H
#define OBSERVABILITY_API_METRICS_METER_H

#include <cstdint>
#include <memory>

#include "metrics/api/gauge.h"
#include "metrics/api/counter.h"
#include "metrics/api/observe_result_t.h"
#include "metrics/api/observable_instrument.h"
#include "metrics/api/alarm.h"

namespace observability::api::metrics {

class Meter {
public:
    virtual ~Meter() = default;
    virtual std::unique_ptr<Gauge<uint64_t>> CreateUInt64Gauge(const std::string &name,
                                                               const std::string &description = "",
                                                               const std::string &unit = "") noexcept = 0;
    virtual std::unique_ptr<Gauge<double>> CreateDoubleGauge(const std::string &name,
                                                             const std::string &description = "",
                                                             const std::string &unit = "") noexcept = 0;
    virtual std::shared_ptr<ObservableInstrument> CreateUint64ObservableCounter(const std::string &name,
                                                                                const std::string &description,
                                                                                const std::string &unit,
                                                                                const uint32_t interval,
                                                                                const CallbackPtr &callback)
                                                                                noexcept = 0;
    virtual std::shared_ptr<ObservableInstrument> CreateDoubleObservableGauge(const std::string &name,
                                                                            const std::string &description,
                                                                            const std::string &unit,
                                                                            const uint32_t interval,
                                                                            const CallbackPtr &callback)
                                                                            noexcept = 0;

    virtual std::unique_ptr<Counter<uint64_t>> CreateUInt64Counter(const std::string &name,
                                                                   const std::string &description = "",
                                                                   const std::string &unit = "") noexcept = 0;
    virtual std::unique_ptr<Counter<double>> CreateDoubleCounter(const std::string &name,
                                                                 const std::string &description = "",
                                                                 const std::string &unit = "") noexcept = 0;

    virtual std::unique_ptr<Alarm> CreateAlarm(const std::string &name,
                                               const std::string &description = "") noexcept = 0;
};

}  // namespace observability::api::metrics

#endif