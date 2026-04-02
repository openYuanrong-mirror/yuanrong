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

#ifndef OBSERVABILITY_SDK_METRICS_METER_CONTEXT_H
#define OBSERVABILITY_SDK_METRICS_METER_CONTEXT_H

#include <memory>
#include <mutex>
#include <unordered_map>
#include <vector>

#include "metrics/sdk/meter.h"
#include "metrics/sdk/metric_processor.h"
#include "metrics/sdk/metric_pusher.h"

namespace observability::sdk::metrics {

class MeterContext : public std::enable_shared_from_this<MeterContext> {
public:
    MeterContext() noexcept;
    ~MeterContext() = default;
    void AddMeter(const std::shared_ptr<Meter> &meter) noexcept;
    std::vector<std::shared_ptr<Meter>> GetMeters() noexcept;

    void AddMetricProcessor(const std::shared_ptr<MetricProcessor> &processor) noexcept;
    std::vector<std::shared_ptr<PusherHandle>> GetPushers() noexcept;

private:
    std::vector<std::shared_ptr<Meter>> meters_;
    std::mutex meterLock_;
    std::vector<std::shared_ptr<PusherHandle>> pushers_;
    std::mutex pusherLock_;
};
}  // namespace observability::sdk::metrics

#endif