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

#ifndef OBSERVABILITY_API_METRICS_METER_PROVIDER_H
#define OBSERVABILITY_API_METRICS_METER_PROVIDER_H

#include <memory>

namespace observability::api::metrics {

class Meter;

class MeterProvider {
public:
    virtual ~MeterProvider() = default;

    virtual std::shared_ptr<Meter> GetMeter(const std::string &meterName) noexcept = 0;
};
}  // namespace observability::api::metrics

#endif