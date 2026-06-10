/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2024-2024. All rights reserved.
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
#include <boost/beast/http.hpp>

#include "mock/mock_security.h"
#include "httpserver/async_https_server.h"
#include "src/libruntime/libruntime_manager.h"
#define private public

using namespace YR::Libruntime;
using namespace YR::utility;
using namespace testing;

namespace YR {
namespace test {
class LibruntimeManagerTest : public testing::Test {
public:
    LibruntimeManagerTest(){};
    ~LibruntimeManagerTest(){};
    void SetUp() override {}
    void TearDown() override {}
};

TEST_F(LibruntimeManagerTest, InitFinalizeTest)
{
    YR::Libruntime::LibruntimeConfig libConfig;
    libConfig.inCluster = true;
    libConfig.isDriver = true;
    libConfig.jobId = YR::utility::IDGenerator::GenApplicationId();
    libConfig.functionSystemIpAddr = "127.0.0.1";
    libConfig.functionSystemPort = 1110;
    libConfig.dataSystemIpAddr = "127.0.0.1";
    libConfig.dataSystemPort = 1100;
    auto rt = LibruntimeManager::Instance().GetLibRuntime("");
    ASSERT_EQ(rt, nullptr);
    bool isInitialized = LibruntimeManager::Instance().IsInitialized("");
    ASSERT_FALSE(isInitialized);
    auto errInfo = LibruntimeManager::Instance().Init(libConfig, "");
    rt = LibruntimeManager::Instance().GetLibRuntime("");
    ASSERT_EQ(rt, nullptr) << errInfo.Code() << errInfo.Msg();
    isInitialized = LibruntimeManager::Instance().IsInitialized("");
    ASSERT_FALSE(isInitialized) << errInfo.Code() << errInfo.Msg();

    LibruntimeManager::Instance().Finalize("");
    rt = LibruntimeManager::Instance().GetLibRuntime("");
    ASSERT_EQ(rt, nullptr);
    isInitialized = LibruntimeManager::Instance().IsInitialized("");
    ASSERT_FALSE(isInitialized);
}

TEST_F(LibruntimeManagerTest, InitFailedWhenInputInvalidRecycleTime)
{
    YR::Libruntime::LibruntimeConfig libConfig;
    libConfig.recycleTime = 0;
    auto errInfo = LibruntimeManager::Instance().Init(libConfig, "");
    ASSERT_FALSE(errInfo.OK());
    libConfig.recycleTime = 3001;
    errInfo = LibruntimeManager::Instance().Init(libConfig, "");
    ASSERT_FALSE(errInfo.OK());
}

TEST_F(LibruntimeManagerTest, HandleInitializedTest)
{
    YR::Libruntime::LibruntimeConfig libConfig;
    libConfig.functionIds[libruntime::LanguageType::Cpp] = "cpp";
    auto errInfo = LibruntimeManager::Instance().HandleInitialized(libConfig, "test");
    ASSERT_EQ(errInfo.OK(), true);
}

// Test Fixture
class LibruntimeManagerTest2 : public ::testing::Test {
public:
    void SetUp() override {
        httpsServer_ = std::make_shared<AsyncHttpsServer>();
        libruntimeManager_ = &YR::Libruntime::LibruntimeManager::Instance();
    }

    void TearDown() override {
        if (libruntimeManager_ != nullptr) {
            libruntimeManager_->StopTokenRefresh();
        }
    }

private:
    std::shared_ptr<AsyncHttpsServer> httpsServer_;
    std::string ip_ = "127.0.0.1";
    unsigned short port_ = 12346;
    int threadNum = 8;
    YR::Libruntime::LibruntimeManager* libruntimeManager_;
    std::shared_ptr<LibruntimeConfig> librConfig_;
};

std::shared_ptr<LibruntimeConfig> ConstructLibruntimeConfig()
{
    std::shared_ptr<LibruntimeConfig> librtCfg = std::make_shared<LibruntimeConfig>();
    librtCfg->enableMTLS = true;
    librtCfg->verifyFilePath = "./test/data/cert/ca.crt";
    librtCfg->certificateFilePath = "./test/data/cert/client.crt";
    std::strcpy(librtCfg->privateKeyPaaswd, "test");
    librtCfg->privateKeyPath = "./test/data/cert/client.key";
    // The serverName is not verified.
    librtCfg->serverName = "test";
    return librtCfg;
}

std::shared_ptr<ssl::context> ConstructSslContext()
{
    try {
        auto ctx = std::make_shared<ssl::context>(ssl::context::tlsv12);
        ctx->set_options(boost::asio::ssl::context::default_workarounds | boost::asio::ssl::context::no_sslv2);
        ctx->load_verify_file("./test/data/cert/ca.crt");
        ctx->use_certificate_chain_file("./test/data/cert/server.crt");
        ctx->set_password_callback(
            [](std::size_t max_length, ssl::context_base::password_purpose purpose) { return "test"; });
        ctx->use_private_key_file("./test/data/cert/server.key", ssl::context::pem);
        return ctx;
    } catch (const std::exception &e) {
        std::cerr << e.what() << std::endl;
        return nullptr;
    }
}

TEST_F(LibruntimeManagerTest2, InitTokenManager)
{
    librConfig_ = std::make_shared<LibruntimeConfig>();
    librConfig_->iamAddress = "http://127.0.0.1:12345";
    auto result = libruntimeManager_->InitTokenManager(librConfig_, nullptr);
    EXPECT_TRUE(result.OK());
}

TEST_F(LibruntimeManagerTest2, SchedulerTokenRefresh)
{
    auto ctx = ConstructSslContext();
    ASSERT_TRUE(ctx != nullptr);
    if (httpsServer_->StartServer(ip_, port_, threadNum, ctx)) {
        std::cout << "start https server success" << std::endl;
    } else {
        std::cout << "start https server failed" << std::endl;
    }
    auto librtCfg = ConstructLibruntimeConfig();
    librtCfg->httpIocThreadsNum = 5;
    librtCfg->iamAddress = "https://127.0.0.1:12346";
    auto tokenManager = std::make_shared<TokenManager>(librtCfg, 3);
    auto initErr = tokenManager->Init();
    EXPECT_TRUE(initErr.OK());
    libruntimeManager_->tokenManager_ = tokenManager;
    auto mockSecurity = std::make_shared<MockSecurity>();

    libruntimeManager_->SchedulerTokenRefresh(mockSecurity);
}

TEST_F(LibruntimeManagerTest2, StopTokenRefresh_CancelTimer)
{
    libruntimeManager_->tokenRefreshTimer_ = YR::utility::ExecuteByGlobalTimer(
        []() { return; },
        10,
        1
    );
    libruntimeManager_->StopTokenRefresh();
    EXPECT_EQ(libruntimeManager_->tokenRefreshTimer_, nullptr);
}
}  // namespace test
}  // namespace YR