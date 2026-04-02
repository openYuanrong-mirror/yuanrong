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

#include "metrics/sdk/metric_pusher.h"

#include "metrics/sdk/instruments.h"

namespace observability::sdk::metrics {

MetricPusher::MetricPusher(const std::weak_ptr<MeterContext> &context,
                           const std::shared_ptr<MetricPushProcessor> &processor)
    : meterContext_(context), processor_(processor)
{
}

void MetricPusher::Push(const MetricData &metricData)
{
    if (processor_ == nullptr) {
        return;
    }
    processor_->Export(metricData);
}

AggregationTemporality MetricPusher::GetAggregationTemporality(InstrumentType instrumentType) noexcept
{
    if (processor_ == nullptr) {
        return AggregationTemporality::UNSPECIFIED;
    }
    return processor_->GetAggregationTemporality(instrumentType);
}

}  // namespace observability::sdk::metrics