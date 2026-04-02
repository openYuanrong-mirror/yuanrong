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

#ifndef OBSERVABILITY_SDK_METRICS_METRIC_PUSHER_H
#define OBSERVABILITY_SDK_METRICS_METRIC_PUSHER_H

#include <memory>

#include "metrics/sdk/meter.h"
#include "metrics/sdk/meter_provider.h"
#include "metrics/sdk/metric_processor.h"
namespace observability::sdk::metrics {

class MetricPushProcessor;
class MeterContext;
struct MetricData;

class PusherHandle {
public:
    virtual ~PusherHandle() = default;
    virtual void Push(const MetricData &metricData) = 0;
    virtual AggregationTemporality GetAggregationTemporality(InstrumentType instrumentType) noexcept = 0;
};

class MetricPusher : public PusherHandle {
public:
    MetricPusher(const std::weak_ptr<MeterContext> &context, const std::shared_ptr<MetricPushProcessor> &processor);
    ~MetricPusher() override = default;
    void Push(const MetricData &metricData) override;
    AggregationTemporality GetAggregationTemporality(InstrumentType instrumentType) noexcept override;

private:
    std::weak_ptr<MeterContext> meterContext_;
    std::shared_ptr<MetricPushProcessor> processor_;
    std::vector<MetricData> metricDataVec_;
};

}  // namespace observability::sdk::metrics
#endif
