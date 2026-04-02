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

#ifndef OBSERVABILITY_SDK_METRICS_INSTRUMENTS_H
#define OBSERVABILITY_SDK_METRICS_INSTRUMENTS_H

#include <memory>
#include <string>

#include "metrics/api/observable_instrument.h"

namespace observability::sdk::metrics {

enum class InstrumentType { COUNTER, HISTOGRAM, GAUGE };

enum class InstrumentValueType { UINT64, INT64, DOUBLE };

enum class AggregationTemporality { UNSPECIFIED, DELTA, CUMULATIVE };

struct InstrumentDescriptor {
    std::string name;
    std::string description;
    std::string unit;
    InstrumentType type = InstrumentType::GAUGE;
    InstrumentValueType valueType = InstrumentValueType::DOUBLE;
};

class SyncMetricRecorder;
class SyncInstrument {
public:
    SyncInstrument(const InstrumentDescriptor &instrumentDescriptor, std::unique_ptr<SyncMetricRecorder> &&recorder);

    virtual ~SyncInstrument() = default;

protected:
    InstrumentDescriptor instrumentDescriptor_;
    std::unique_ptr<SyncMetricRecorder> recorder_;
};

class ObservableInstrument : public api::metrics::ObservableInstrument {
public:
    explicit ObservableInstrument(InstrumentDescriptor instrumentDescriptor)
        : instrumentDescriptor_(instrumentDescriptor)
    {
    }
    ~ObservableInstrument() override = default;

private:
    InstrumentDescriptor instrumentDescriptor_;
};
}  // namespace observability::sdk::metrics

#endif