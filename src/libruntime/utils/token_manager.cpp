/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.
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

#include "token_manager.h"

#include <future>
#include <utility>

#include "src/libruntime/utils/utils.h"

namespace YR {
namespace Libruntime {
TokenManager::TokenManager(std::shared_ptr<LibruntimeConfig> &librtConfig, int retryTime)
{
    this->librtConfig = librtConfig;
    this->initRetryTime_ = retryTime;
}

bool TokenManager::IsInitToken()
{
    if (librtConfig->iamAddress.empty()) {
        YRLOG_DEBUG("skip init token, because iam address is empty");
        return false;
    }
    if (!librtConfig->token.Empty()) {
        YRLOG_DEBUG("skip init token, because token is not empty");
        return false;
    }
    auto credentialType = YR::GetEnvValue(std::string(ENV_CREDENTIAL_TYPE));
    if (credentialType != CREDENTIAL_TYPE_TOKEN) {
        YRLOG_DEBUG("skip init token, because credential type: {} is not {}", credentialType, CREDENTIAL_TYPE_TOKEN);
        return false;
    }
    if (Config::Instance().YR_FAAS_DRIVER_MOD() != FAAS_DRIVER_MOD_MICROSERVICE) {
        YRLOG_DEBUG("skip init token, because YR_FAAS_DRIVER_MOD is not {}", FAAS_DRIVER_MOD_MICROSERVICE);
        return false;
    }
    this->initRetryTime_ = std::numeric_limits<int>::max();
    return true;
}

YR::Libruntime::ErrorInfo TokenManager::Init()
{
    YRLOG_DEBUG("start init http client");
    this->httpClient = std::make_shared<YR::Libruntime::ClientManager>(this->librtConfig);
    std::string addr = this->librtConfig->iamAddress;
    if (addr.find(HTTPS_PROTOCOL_PREFIX) == 0) {
        addr = addr.substr(HTTPS_PROTOCOL_PREFIX.size());
    } else if (addr.find(HTTP_PROTOCOL_PREFIX) == 0) {
        addr = addr.substr(HTTP_PROTOCOL_PREFIX.size());
    }
    int32_t port = 0;
    YR::ParseIpAddr(addr, this->ip_, port);
    if (port == 0) {
        port = HTTPS_DEFAULT_PORT;
    }
    this->port_ = std::to_string(port);
    YRLOG_DEBUG("prepare init http client, ip {}, port {}", this->ip_, this->port_);
    // 预防启动时，iam 还未拉起，一直重试到健康检查超时
    auto err = this->httpClient->Init(ConnectionParam{this->ip_, this->port_},
                                      this->connectedClientsCnt_, this->initRetryTime_);
    if (!err.OK()) {
        YRLOG_ERROR("init http client failed, code id {}, msg is {}", fmt::underlying(err.Code()), err.Msg());
        return err;
    }
    YRLOG_DEBUG("init http client finish");
    return {};
}

std::pair<std::shared_ptr<TokenSalt>, ErrorInfo> TokenManager::RequireToken()
{
    if (this->httpClient == nullptr) {
        return std::make_pair(nullptr, ErrorInfo(ERR_INNER_SYSTEM_ERROR, "httpClient is null"));
    }
    std::unordered_map<std::string, std::string> headers;
    headers.emplace(std::string(HEADER_TENANT_ID_KEY), std::string(SYSTEM_FUNCTION_TENANT_ID));
    auto reqId = std::make_shared<std::string>(YR::utility::IDGenerator::GenRequestId());
    auto promise = std::make_shared<std::promise<std::unordered_map<std::string, std::string>>>();
    auto future = promise->get_future();
    HttpCallbackFunctionV2 httpCallbackFunc =
            [promise, reqId](const std::string &result, const boost::beast::error_code &errCode, const uint statusCode,
                             const std::unordered_map<std::string, std::string> &headers) {
        std::stringstream errSS;
        errSS << "require token from iam failed, ";
        if (errCode) {
            errSS << "network error, error_code: " << errCode.message() << ", requestId: " << *reqId;
            promise->set_exception(std::make_exception_ptr(std::runtime_error(errSS.str())));
            return;
        } else if (!IsResponseSuccessful(statusCode)) {
            errSS << "failed response status_code: " << std::to_string(statusCode) << ", result: " << result
                  << ", requestId: " << *reqId;
            promise->set_exception(std::make_exception_ptr(std::runtime_error(errSS.str())));
            return;
        }
        YRLOG_DEBUG("require token from iam success, requestId: {}", *reqId);
        promise->set_value(headers);
    };
    this->httpClient->SubmitInvokeRequest(GET, std::string(REQUIRE_ENCRYPT_TOKEN_PATH), headers, {}, reqId,
                                          httpCallbackFunc);
    return ParseRespToken(std::move(future));
}

std::pair<std::shared_ptr<TokenSalt>, ErrorInfo> TokenManager::ParseRespToken(
    std::future<std::unordered_map<std::string, std::string>> future)
{
    auto result = std::make_shared<TokenSalt>();
    try {
        std::unordered_map<std::string, std::string> response = future.get();
        result->token = response.at(std::string(HEADER_AUTH_KEY));
        result->salt = response.at(std::string(HEADER_TENANT_SALT_KEY));
        std::string expireStr = response.at(std::string(HEADER_EXPIRED_TIME_SPAN));
        if (!expireStr.empty()) {
            result->expiredTimeStamp = std::stoull(expireStr);
        }
        YRLOG_DEBUG("parse resp token ok");
        return std::make_pair(result, ErrorInfo());
    } catch (const std::exception &e) {
        std::stringstream ss;
        ss << "get token failed, err: " << e.what();
        YRLOG_ERROR(ss.str());
        return std::make_pair(result, ErrorInfo(ERR_INNER_SYSTEM_ERROR, ss.str()));
    }
}
}  // namespace Libruntime
}  // namespace YR