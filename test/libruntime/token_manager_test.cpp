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

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <memory>
#include <unordered_map>
#include <string>

#include "httpserver/async_http_server.h"
#include "src/libruntime/utils/token_manager.h"

#define private public
using namespace YR::Libruntime;
using namespace testing;
using namespace YR::utility;

namespace YR {
namespace Test {
class TokenManagerTest : public ::testing::Test {
public:
    void SetUp() override {
        httpServer_ = std::make_shared<AsyncHttpServer>();
    }

    void TearDown() override {
        if (httpServer_) {
            httpServer_.reset();
        }
    }
private:
    std::shared_ptr<AsyncHttpServer> httpServer_;
    std::string ip_ = "127.0.0.1";
    unsigned short port_ = 12345;
    int threadNum = 8;
};

class MockClientManager : public ClientManager {
public:
    explicit MockClientManager(const std::shared_ptr<LibruntimeConfig> &librtCfg) : ClientManager(librtCfg),
                                                                                    librtConfig_(librtCfg) {}

    YR::Libruntime::ErrorInfo Init(const ConnectionParam& param, uint32_t connectedClientsCnt, int retryTime) {
        // 模拟初始化成功
        return {};
    }

    void SubmitInvokeRequest(const std::string& method, const std::string& path,
                             const std::unordered_map<std::string, std::string>& headers,
                             const std::string& body, const std::shared_ptr<std::string>& reqId,
                             const HttpCallbackFunctionV2& callback) {
        // 模拟回调函数
        std::unordered_map<std::string, std::string> mockHeaders = {
            {std::string(YR::Libruntime::HEADER_AUTH_KEY), "mock_token"},
            {std::string(YR::Libruntime::HEADER_TENANT_SALT_KEY), "mock_salt"},
            {std::string(YR::Libruntime::HEADER_EXPIRED_TIME_SPAN), "1234567890"}
        };
        callback("", boost::beast::error_code(), 200, mockHeaders);
    }

private:
    std::shared_ptr<LibruntimeConfig> librtConfig_;
};

TEST_F(TokenManagerTest, IsInitToken)
{
    auto librtConfig = std::make_shared<LibruntimeConfig>();
    librtConfig->iamAddress = "https://example.com";
    librtConfig->token = "";

    TokenManager tokenManager(librtConfig);
    EXPECT_FALSE(tokenManager.IsInitToken());
}

TEST_F(TokenManagerTest, Init)
{
    auto librtConfig = std::make_shared<LibruntimeConfig>();
    librtConfig->enableMTLS = true;
    librtConfig->iamAddress = "https://example.com";
    librtConfig->token = "";
    auto tokenManager = std::make_shared<TokenManager>(librtConfig, 3);

    auto err = tokenManager->Init();
    EXPECT_FALSE(err.OK());
}

TEST_F(TokenManagerTest, ParseRespToken)
{
    std::unordered_map<std::string, std::string> mockHeaders = {
        {std::string(YR::Libruntime::HEADER_AUTH_KEY), "mock_token"},
        {std::string(YR::Libruntime::HEADER_TENANT_SALT_KEY), "mock_salt"},
        {std::string(YR::Libruntime::HEADER_EXPIRED_TIME_SPAN), "1234567890"}
    };
    std::promise<std::unordered_map<std::string, std::string>> promise;
    promise.set_value(mockHeaders);

    TokenManager tokenManager;
    auto result = tokenManager.ParseRespToken(promise.get_future());
    EXPECT_TRUE(result.second.OK());
    EXPECT_EQ(result.first->token, "mock_token");
    EXPECT_EQ(result.first->salt, "mock_salt");
    EXPECT_EQ(result.first->expiredTimeStamp, 1234567890);
}

TEST_F(TokenManagerTest, RequireToken)
{
    if (httpServer_->StartServer(ip_, port_, threadNum)) {
        std::cout << "start http server success" << std::endl;
    } else {
        std::cout << "start http server failed" << std::endl;
    }
    std::shared_ptr<LibruntimeConfig> librtCfg = std::make_shared<LibruntimeConfig>();
    librtCfg->httpIocThreadsNum = 5;
    librtCfg->iamAddress = "https://127.0.0.1:12345";
    auto tokenManager = std::make_shared<TokenManager>(librtCfg, 3);
    auto initErr = tokenManager->Init();
    EXPECT_TRUE(initErr.OK());

    auto result = tokenManager->RequireToken();
    EXPECT_FALSE(result.second.OK());
    EXPECT_EQ(result.first->token, "");
    EXPECT_EQ(result.first->salt, "");
    EXPECT_EQ(result.first->expiredTimeStamp, 0);
}
}  // namespace test
}  // namespace YR