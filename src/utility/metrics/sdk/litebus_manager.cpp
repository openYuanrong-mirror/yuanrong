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

#include <actor/actor.hpp>
#include <async/asyncafter.hpp>

#include "src/utility/metrics/sdk/include/litebus_manager.h"

namespace observability::sdk::metrics {

bool LiteBusManager::InitLiteBus(const std::string &address, int32_t threadNum, bool enableUDP) noexcept
{
    std::string tcpAddr = address.empty() ? "" : "tcp://" + address;
    std::string udpAddr = enableUDP ? "udp://" + address : "";
    std::cerr << "Initialize LiteBus, tcp addr:" << tcpAddr << "u dp addr: " << udpAddr <<
        " threadNum: " << threadNum << std::endl;
    auto result = litebus::Initialize(tcpAddr, "", udpAddr, "", threadNum);
    if (result != BUS_OK) {
        std::cerr << "LiteBus initialize failed, address:" << address << "result: " << result << std::endl;
        return false;
    }
    liteBusInitialized_ = true;
    return true;
}

void LiteBusManager::FinalizeLiteBus() noexcept
{
    if (liteBusInitialized_) {
        litebus::TerminateAll();
        litebus::Finalize();
        liteBusInitialized_ = false;
    }
}
}
