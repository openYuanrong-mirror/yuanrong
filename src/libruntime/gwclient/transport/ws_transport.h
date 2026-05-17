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

#pragma once

#include <memory>
#include "src/libruntime/gwclient/transport/transport_client.h"

namespace YR {
namespace Libruntime {

// Forward declarations
struct LibruntimeConfig;
class WsTransportImpl;

/**
 * @brief WebSocket implementation of TransportClient
 *
 * This class provides WebSocket transport for create/invoke operations.
 */
class WsTransport : public TransportClient {
public:
    WsTransport();
    ~WsTransport() override;

    ErrorInfo Init(const TransportParam &param) override;
    void SubmitRequest(const std::string &target,
                       const std::unordered_map<std::string, std::string> &headers,
                       const std::string &body,
                       const std::shared_ptr<std::string> &requestId,
                       const TransportCallback &callback) override;
    bool IsConnected() const override;
    void Stop() override;
    std::string Type() const override;

private:
    std::unique_ptr<WsTransportImpl> impl_;
};

// Factory function to create WebSocket transport
std::shared_ptr<TransportClient> CreateWsTransport();

/**
 * @brief Create and initialize a WsTransport from LibruntimeConfig.
 *
 * Uses config fields (TLS, certs, server address) directly.
 * Only reads YR_ENABLE_WEBSOCKET and YR_WEBSOCKET_TIMEOUT from env.
 *
 * @param config LibruntimeConfig with server address, TLS and cert settings
 * @return initialized WsTransport, or nullptr if WS is disabled / init fails
 */
std::shared_ptr<TransportClient> CreateWsTransportFromConfig(const std::shared_ptr<LibruntimeConfig> &config);

}  // namespace Libruntime
}  // namespace YR