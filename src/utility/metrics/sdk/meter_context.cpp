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

#include "metrics/sdk/meter_context.h"
#include "metrics/sdk/metric_pusher.h"

namespace observability::sdk::metrics {

MeterContext::MeterContext() noexcept
{
}

void MeterContext::AddMeter(const std::shared_ptr<Meter> &meter) noexcept
{
    std::lock_guard<std::mutex> guard(meterLock_);
    meters_.push_back(meter);
}

std::vector<std::shared_ptr<Meter>> MeterContext::GetMeters() noexcept
{
    std::lock_guard<std::mutex> guard(meterLock_);
    return meters_;
}

void MeterContext::AddMetricProcessor(const std::shared_ptr<MetricProcessor> &processor) noexcept
{
    std::lock_guard<std::mutex> guard(pusherLock_);
    if (processor->GetProcessorType() == MetricProcessor::ProcessorType::PUSH) {
        auto pushProcessor = std::dynamic_pointer_cast<MetricPushProcessor>(processor);
        auto pusher = std::make_shared<MetricPusher>(shared_from_this(), pushProcessor);
        pushers_.push_back(pusher);
    } else if (processor->GetProcessorType() == MetricProcessor::ProcessorType::PULL) {
    } else {
    }
}

std::vector<std::shared_ptr<PusherHandle>> MeterContext::GetPushers() noexcept
{
    std::lock_guard<std::mutex> guard(pusherLock_);
    return pushers_;
}

}  // namespace observability::sdk::metrics