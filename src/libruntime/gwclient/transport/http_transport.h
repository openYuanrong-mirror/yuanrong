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
#include "src/libruntime/gwclient/http/http_client.h"

namespace YR {
namespace Libruntime {

/**
 * @brief HTTP implementation of TransportClient
 *
 * This class wraps the existing HttpClient to provide HTTP transport.
 * Can be initialized with existing HttpClient or with TransportParam.
 */
class HttpTransport : public TransportClient {
public:
    HttpTransport() = default;

    // Construct with existing HttpClient (wrapper mode)
    explicit HttpTransport(std::shared_ptr<HttpClient> httpClient);

    ~HttpTransport() override { Stop(); }

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
    std::shared_ptr<HttpClient> httpClient_;
    bool initialized_{false};
    bool wrapperMode_{false};  // true if wrapping existing HttpClient
};

// Factory function to create HTTP transport
std::shared_ptr<TransportClient> CreateHttpTransport();

}  // namespace Libruntime
}  // namespace YR