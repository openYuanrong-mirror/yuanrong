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

#ifndef OBSERVABILITY_API_METRICS_PROVIDER_H
#define OBSERVABILITY_API_METRICS_PROVIDER_H

#include <memory>
#include <mutex>

#include "metrics/api/null.h"

namespace observability::api::metrics {

class MeterProvider;

class Provider {
public:
    static std::shared_ptr<MeterProvider> GetMeterProvider() noexcept
    {
        std::lock_guard<std::mutex> guard(GetLock());
        return std::shared_ptr<MeterProvider>(GetProvider());
    }

    static void SetMeterProvider(std::shared_ptr<MeterProvider> tp) noexcept
    {
        std::lock_guard<std::mutex> guard(GetLock());
        GetProvider() = tp;
    }

private:
    static std::shared_ptr<MeterProvider> &GetProvider() noexcept
    {
        static std::shared_ptr<MeterProvider> provider = std::make_shared<NullMeterProvider>();
        return provider;
    }

    static std::mutex &GetLock() noexcept
    {
        static std::mutex lock;
        return lock;
    }
};

}  // namespace observability::api::metrics

#endif