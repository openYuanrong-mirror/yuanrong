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

#include "src/libruntime/gwclient/transport/http_transport.h"

#include "src/dto/config.h"
#include "src/libruntime/gwclient/http/client_manager.h"
#include "src/libruntime/libruntime_config.h"
#include "src/utility/logger/logger.h"

namespace beast = boost::beast;
namespace http = beast::http;

namespace YR {
namespace Libruntime {

HttpTransport::HttpTransport(std::shared_ptr<HttpClient> httpClient)
    : httpClient_(std::move(httpClient)), initialized_(true), wrapperMode_(true)
{
}

ErrorInfo HttpTransport::Init(const TransportParam &param)
{
    if (initialized_) {
        return ErrorInfo();
    }

    if (wrapperMode_) {
        return ErrorInfo();
    }

    // Build LibruntimeConfig for ClientManager
    auto librtConfig = std::make_shared<LibruntimeConfig>();
    librtConfig->enableTLS = param.enableTLS;
    librtConfig->enableMTLS = param.enableMTLS;
    librtConfig->certificateFilePath = param.certFile;
    librtConfig->privateKeyPath = param.keyFile;
    librtConfig->verifyFilePath = param.caFile;
    librtConfig->maxConnSize = Config::Instance().YR_HTTP_CONNECTION_NUM();
    librtConfig->httpIocThreadsNum = 1;

    // Build ConnectionParam
    ConnectionParam connParam;
    connParam.ip = param.host;
    connParam.port = std::to_string(param.port);
    connParam.timeoutSec = param.timeoutSec;

    // Create and initialize ClientManager
    auto clientManager = std::make_shared<ClientManager>(librtConfig);
    auto err = clientManager->Init(connParam);
    if (!err.OK()) {
        YRLOG_ERROR("HttpTransport init failed: {}", err.Msg());
        return err;
    }

    httpClient_ = clientManager;
    initialized_ = true;
    YRLOG_INFO("HttpTransport initialized, host: {}:{}, TLS: {}, mTLS: {}",
               param.host, param.port, param.enableTLS, param.enableMTLS);
    return ErrorInfo();
}

void HttpTransport::SubmitRequest(const std::string &target,
                                   const std::unordered_map<std::string, std::string> &headers,
                                   const std::string &body,
                                   const std::shared_ptr<std::string> &requestId,
                                   const TransportCallback &callback)
{
    if (!initialized_ || !httpClient_) {
        callback("", ErrorInfo(ErrorCode::ERR_INNER_SYSTEM_ERROR, ModuleCode::RUNTIME,
                               "HttpTransport not initialized"), 0);
        return;
    }

    auto httpCallback = [callback](const std::string &result, const boost::beast::error_code &ec,
                                   uint statusCode) {
        ErrorInfo err;
        if (ec) {
            err = ErrorInfo(ErrorCode::ERR_INNER_COMMUNICATION, ModuleCode::RUNTIME,
                            "HTTP error: " + ec.message());
        }
        callback(result, err, statusCode);
    };

    httpClient_->SubmitInvokeRequest(http::verb::post, target, headers, body, requestId, httpCallback);
}

bool HttpTransport::IsConnected() const
{
    return initialized_ && httpClient_ != nullptr;
}

void HttpTransport::Stop()
{
    // Only stop if we own the client (not in wrapper mode)
    if (!wrapperMode_ && httpClient_) {
        httpClient_->Stop();
    }
    httpClient_.reset();
    initialized_ = false;
}

std::string HttpTransport::Type() const { return "HTTP"; }

std::shared_ptr<TransportClient> CreateHttpTransport()
{
    return std::make_shared<HttpTransport>();
}

}  // namespace Libruntime
}  // namespace YR