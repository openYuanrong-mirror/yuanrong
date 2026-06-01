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

#include <functional>
#include <stdexcept>
#include <string>
#include <unordered_map>

#include <boost/asio/ssl.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include "absl/synchronization/mutex.h"
#include "src/dto/config.h"
#include "src/libruntime/err_type.h"
#include "src/libruntime/utils/utils.h"
#include "src/utility/logger/logger.h"
#include "src/utility/string_utility.h"
namespace http = boost::beast::http;
namespace ssl = boost::asio::ssl;
namespace beast = boost::beast;
namespace asio = boost::asio;
namespace YR {
namespace Libruntime {
using HttpCallbackFunction = std::function<void(const std::string &, const boost::beast::error_code &, const uint)>;
const http::verb POST = http::verb::post;
const http::verb DELETE = http::verb::delete_;
const http::verb GET = http::verb::get;
const http::verb PUT = http::verb::put;
extern const int DEFAULT_HTTP_VERSION;
extern const uint HTTP_CONNECTION_ERROR_CODE;
const int CONNECTION_NO_TIMEOUT = -1;
extern const char *HTTP_CONNECTION_ERROR_MSG;
struct ConnectionParam {
    std::string ip;
    std::string port;
    int idleTime{120};
    int timeoutSec = CONNECTION_NO_TIMEOUT;
};

inline std::string GetProxyUrlFromEnv(bool forHttps)
{
    if (!Config::Instance().YR_ENABLE_HTTP_PROXY()) {
        return "";
    }
    // Match curl: scheme-specific proxy first, then fallback to the other.
    if (forHttps) {
        for (const char *key : {"https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"}) {
            const std::string val = YR::GetEnvValue(key);
            if (!val.empty()) {
                return val;
            }
        }
    } else {
        for (const char *key : {"http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"}) {
            const std::string val = YR::GetEnvValue(key);
            if (!val.empty()) {
                return val;
            }
        }
    }
    return "";
}

inline void ConnectWithOptionalProxy(beast::tcp_stream &stream, asio::ip::tcp::resolver &resolver,
                                     const ConnectionParam &param, bool forHttps)
{
    const std::string proxyUrl = GetProxyUrlFromEnv(forHttps);

    if (param.timeoutSec != CONNECTION_NO_TIMEOUT) {
        stream.expires_after(std::chrono::seconds(param.timeoutSec));
    }

    if (!proxyUrl.empty()) {
        std::string url = proxyUrl;
        const std::string schemeDelimiter = "://";
        const auto schemePos = url.find(schemeDelimiter);
        if (schemePos != std::string::npos) {
            url = url.substr(schemePos + schemeDelimiter.size());
        }

        std::string proxyAuthorization;
        const auto authPos = url.rfind('@');
        if (authPos != std::string::npos) {
            proxyAuthorization = "Basic " + YR::utility::EncodedToString(url.substr(0, authPos));
            url = url.substr(authPos + 1);
        }

        std::string proxyHost;
        std::string proxyPort = "80";
        const auto portPos = url.rfind(':');
        if (portPos != std::string::npos) {
            proxyHost = url.substr(0, portPos);
            proxyPort = url.substr(portPos + 1);
        } else {
            proxyHost = url;
        }

        YRLOG_INFO("connecting to {}:{} via proxy {}:{}", param.ip, param.port, proxyHost, proxyPort);
        stream.connect(resolver.resolve(proxyHost, proxyPort));

        const std::string connectTarget = param.ip + ":" + param.port;
        http::request<http::empty_body> req{http::verb::connect, connectTarget, 11};
        req.set(http::field::host, connectTarget);
        if (!proxyAuthorization.empty()) {
            req.set(http::field::proxy_authorization, proxyAuthorization);
        }
        http::write(stream, req);

        beast::flat_buffer buffer;
        http::response_parser<http::empty_body> parser;
        parser.body_limit(0);
        http::read(stream, buffer, parser);
        if (parser.get().result() != http::status::ok) {
            throw std::runtime_error("HTTP CONNECT via proxy failed, status " +
                                     std::to_string(parser.get().result_int()));
        }
    } else {
        stream.connect(resolver.resolve(param.ip, param.port));
    }

    if (param.timeoutSec != CONNECTION_NO_TIMEOUT) {
        stream.expires_never();
    }
}

class HttpClient {
public:
    virtual ~HttpClient() = default;
    virtual ErrorInfo Init(const ConnectionParam &param) = 0;
    virtual void SubmitInvokeRequest(const http::verb &method, const std::string &target,
                                     const std::unordered_map<std::string, std::string> &headers,
                                     const std::string &body, const std::shared_ptr<std::string> requestId,
                                     const HttpCallbackFunction &receiver) = 0;

    virtual ErrorInfo ReInit(const std::shared_ptr<std::string> requestId)
    {
        GracefulExit();
        const int totalRetryCount = YR::Libruntime::Config::Instance().MAX_HTTP_RETRY_TIME();
        const int maxTimeoutSec = YR::Libruntime::Config::Instance().MAX_HTTP_TIMEOUT_SEC();
        int timeoutSec = YR::Libruntime::Config::Instance().INITIAL_HTTP_CONNECT_SEC();
        YRLOG_DEBUG("client start reinit. initTimeoutSec: {} maxTimeoutSec: {} totalRetryCount: {} requestId: {}",
            timeoutSec, maxTimeoutSec, totalRetryCount, *requestId);
        int retryCount = 0;
        int backoffFactor = 2;
        ErrorInfo err;
        while (retryCount < totalRetryCount) {
            connParam_.timeoutSec = timeoutSec;
            err = Init(connParam_);
            if (err.OK()) {
                YRLOG_DEBUG("client reinit success, requestId: {}", *requestId);
                connParam_.timeoutSec = CONNECTION_NO_TIMEOUT;
                return err;
            }
            retryCount++;
            if (timeoutSec != CONNECTION_NO_TIMEOUT) {
                timeoutSec = std::min(timeoutSec * backoffFactor, maxTimeoutSec);
            }
            YRLOG_DEBUG("retry count {}, requestId: {} init err: {}", retryCount, *requestId, err.Msg());
        }
        connParam_.timeoutSec = CONNECTION_NO_TIMEOUT;
        return err;
    }

    virtual void Stop() {}

    virtual void GracefulExit() noexcept {}

    bool SetUnavailable()
    {
        absl::WriterMutexLock l(&mu_);
        if (isUsed_) {
            return false;
        }
        isUsed_ = true;
        return true;
    }

    void SetAvailable()
    {
        std::function<void()> releaseCallback;
        {
            absl::WriterMutexLock l(&mu_);
            isUsed_ = false;
            releaseCallback = std::move(onRelease_);
        }
        if (releaseCallback) {
            releaseCallback();
        }
    }

    void SetOnRelease(std::function<void()> callback)
    {
        absl::WriterMutexLock l(&mu_);
        onRelease_ = std::move(callback);
    }

    void ResetConnActive()
    {
        absl::WriterMutexLock l(&mu_);
        lastActiveTime_ = std::chrono::high_resolution_clock::now();
        isConnectionAlive_ = true;
    }

    void ResetConnActiveTime()
    {
        absl::WriterMutexLock l(&mu_);
        lastActiveTime_ = std::chrono::high_resolution_clock::now();
    }

    void SetConnInActive()
    {
        absl::WriterMutexLock l(&mu_);
        isConnectionAlive_ = false;
    }

    bool Available() const
    {
        absl::ReaderMutexLock l(&mu_);
        return !this->isUsed_;
    };

    bool IsConnActive() const
    {
        absl::ReaderMutexLock l(&mu_);
        auto current = std::chrono::high_resolution_clock::now();
        auto idle = std::chrono::duration_cast<std::chrono::seconds>(current - this->lastActiveTime_).count();
        return isConnectionAlive_ && idle < idleTime_;
    };

    void CheckResponseHeaderAndReset()
    {
        auto headers = resParser_->get().base();
        if (auto it = headers.find("Connection"); it != headers.end() && it->value() == "close") {
            SetConnInActive();
        }
        resParser_.reset();
        buf_.clear();
        req_.clear();
        ResetConnActiveTime();
        SetAvailable();
    };

protected:
    ConnectionParam connParam_;
    HttpCallbackFunction callback_;
    beast::flat_buffer buf_;
    std::shared_ptr<http::response_parser<http::string_body>> resParser_;
    http::request<http::string_body> req_;
    bool isUsed_{true};
    bool isConnectionAlive_{false};
    std::chrono::time_point<std::chrono::high_resolution_clock> lastActiveTime_;
    bool retried_{false};
    int idleTime_{120};
    std::function<void()> onRelease_;
    mutable absl::Mutex mu_;
};

inline bool IsResponseSuccessful(const uint statusCode)
{
    const uint SUCCESS_CODE_MIN = 200;
    const uint SUCCESS_CODE_MAX = 299;
    return (statusCode >= SUCCESS_CODE_MIN && statusCode <= SUCCESS_CODE_MAX);
}

inline bool IsResponseServerError(const uint statusCode)
{
    const uint SUCCESS_CODE_MIN = 500;
    const uint SUCCESS_CODE_MAX = 599;
    return (statusCode >= SUCCESS_CODE_MIN && statusCode <= SUCCESS_CODE_MAX);
}

inline bool IsResponseClientError(const uint statusCode)
{
    const uint SUCCESS_CODE_MIN = 400;
    const uint SUCCESS_CODE_MAX = 499;
    return (statusCode >= SUCCESS_CODE_MIN && statusCode <= SUCCESS_CODE_MAX);
}
}  // namespace Libruntime
}  // namespace YR