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

#ifndef OBSERVABILITY_SDK_METRICS_LITEBUS_MANAGER_H
#define OBSERVABILITY_SDK_METRICS_LITEBUS_MANAGER_H

#include <memory>
#include <atomic>

namespace observability::sdk::metrics {

class LiteBusManager {
public:
    LiteBusManager()
    {
    };
    ~LiteBusManager()
    {
    };
    bool InitLiteBus(const std::string &address, int32_t threadNum, bool enableUDP = false) noexcept;
    void FinalizeLiteBus() noexcept;

private:
    std::atomic_bool liteBusInitialized_{ false };
};
}
#endif // OBSERVABILITY_SDK_METRICS_LITEBUS_MANAGER_H
