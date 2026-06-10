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

#pragma once

#include <future>

#include "src/libruntime/gwclient/http/client_manager.h"

namespace YR {
namespace Libruntime {
const std::string_view REQUIRE_ENCRYPT_TOKEN_PATH = "/iam-server/v1/token/require";
const std::string_view HEADER_TENANT_ID_KEY = "X-Tenant-ID";
const std::string_view SYSTEM_FUNCTION_TENANT_ID = "0";
const std::string_view HEADER_AUTH_KEY = "X-Auth";
const std::string_view HEADER_TENANT_SALT_KEY = "X-Salt";
const std::string_view HEADER_EXPIRED_TIME_SPAN = "X-Expired-Time-Span";
const std::string_view ENV_CREDENTIAL_TYPE = "IAM_CREDENTIAL_TYPE";
const std::string_view CREDENTIAL_TYPE_TOKEN = "token";

struct TokenSalt {
    std::string token;
    std::string salt;
    int64_t expiredTimeStamp{ 0 };

    std::string toString()
    {
        std::ostringstream oss;
        oss << "token: " << token << ", expiredTimeStamp: " << std::to_string(expiredTimeStamp) << ", salt: " << salt;
        return oss.str();
    }
};

class TokenManager : public std::enable_shared_from_this<TokenManager> {
public:
    TokenManager() = default;
    ~TokenManager() = default;

    explicit TokenManager(std::shared_ptr<LibruntimeConfig> &librtConfig,
                          int retryTime = std::numeric_limits<int>::max());

    bool IsInitToken();

    YR::Libruntime::ErrorInfo Init();

    // 调用 iam 方法
    std::pair<std::shared_ptr<TokenSalt>, ErrorInfo> RequireToken();

    // 解析响应结果 token 方法
    std::pair<std::shared_ptr<TokenSalt>, ErrorInfo> ParseRespToken(
        std::future<std::unordered_map<std::string, std::string>> future);

private:
    std::shared_ptr<YR::Libruntime::ClientManager> httpClient;
    std::shared_ptr<YR::Libruntime::LibruntimeConfig> librtConfig;
    uint32_t connectedClientsCnt_ = 1;
    int initRetryTime_ = RETRY_TIME;
    std::string ip_;
    std::string port_;
};
}  // namespace Libruntime
}  // namespace YR