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

#include <functional>
#include <memory>
#include <string>
#include <unordered_map>

#include "src/libruntime/err_type.h"

namespace YR {
namespace Libruntime {

// Transport callback function type
// Parameters: response body, error info, HTTP status code (0 for non-HTTP transport)
using TransportCallback = std::function<void(const std::string &result, const ErrorInfo &err, uint statusCode)>;

// Transport parameters for initialization
struct TransportParam {
    std::string host;
    int port{0};
    int timeoutSec{30};
    bool enableTLS{false};
    bool enableMTLS{false};
    std::string certFile;
    std::string keyFile;
    std::string caFile;
    std::string authToken;
};

/**
 * @brief Abstract interface for transport layer (HTTP, WebSocket, etc.)
 *
 * This interface provides a unified abstraction for different transport protocols.
 * Implementations include HttpTransport and WsTransport.
 */
class TransportClient {
public:
    virtual ~TransportClient() = default;

    /**
     * @brief Initialize the transport client with parameters
     * @param param Transport parameters
     * @return ErrorInfo indicating success or failure
     */
    virtual ErrorInfo Init(const TransportParam &param) = 0;

    /**
     * @brief Submit a request to the target endpoint
     * @param target The target path (e.g., "/serverless/v1/posix/instance/create")
     * @param headers Request headers
     * @param body Request body (protobuf serialized)
     * @param requestId Unique request identifier for tracking
     * @param callback Callback function invoked when response is received
     */
    virtual void SubmitRequest(const std::string &target,
                               const std::unordered_map<std::string, std::string> &headers,
                               const std::string &body,
                               const std::shared_ptr<std::string> &requestId,
                               const TransportCallback &callback) = 0;

    /**
     * @brief Check if the transport is connected and ready
     * @return true if connected, false otherwise
     */
    virtual bool IsConnected() const = 0;

    /**
     * @brief Stop the transport client and release resources
     */
    virtual void Stop() = 0;

    /**
     * @brief Get the transport type name for logging
     * @return Transport type string (e.g., "HTTP", "WebSocket")
     */
    virtual std::string Type() const = 0;
};

}  // namespace Libruntime
}  // namespace YR