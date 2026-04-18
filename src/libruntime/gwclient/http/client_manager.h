/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2023-2025. All rights reserved.
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

#include <mutex>
#include <queue>
#include <thread>
#include <vector>

#include <boost/asio/strand.hpp>
#include "src/libruntime/gwclient/http/http_client.h"
#include "src/libruntime/libruntime_config.h"

namespace asio = boost::asio;

namespace YR {
namespace Libruntime {

struct PendingRequest {
    http::verb method;
    std::string target;
    std::unordered_map<std::string, std::string> headers;
    std::string body;
    std::shared_ptr<std::string> requestId;
    HttpCallbackFunction receiver;
};

class ClientManager : public HttpClient {
public:
    ClientManager(const std::shared_ptr<LibruntimeConfig> &librtCfg);
    ~ClientManager() override;

    virtual ErrorInfo Init(const ConnectionParam &param) override;
    virtual void SubmitInvokeRequest(const http::verb &method, const std::string &target,
                                     const std::unordered_map<std::string, std::string> &headers,
                                     const std::string &body, const std::shared_ptr<std::string> requestId,
                                     const HttpCallbackFunction &receiver) override;
    void Stop() override;
private:
    // TryDispatch: runs on strand_; attempts to find a free connection and dispatch req.
    // Returns true if dispatched (req consumed), false if all connections are busy.
    bool TryDispatch(const PendingRequest &req);
    // DrainQueue: runs on strand_; dispatches pending requests to any free connection.
    void DrainQueue();
    ErrorInfo InitCtxAndIocThread();
    std::shared_ptr<asio::io_context> ioc;
    std::unique_ptr<boost::asio::executor_work_guard<boost::asio::io_context::executor_type>> work;
    std::vector<std::unique_ptr<std::thread>> asyncRunners;

    ConnectionParam connParam;
    std::vector<std::shared_ptr<HttpClient>> clients;
    uint32_t connectedClientsCnt_{0};
    // strand_ serializes all dispatch / queue operations; no separate mutex needed.
    std::unique_ptr<asio::strand<asio::io_context::executor_type>> strand_;
    std::queue<PendingRequest> pendingQueue_;
    std::shared_ptr<LibruntimeConfig> librtCfg;
    uint32_t maxIocThread;
    bool enableMTLS;
    bool enableTLS_{false};
    uint32_t maxConnSize_;
    bool stopped_{false};
};
}  // namespace Libruntime
}  // namespace YR
