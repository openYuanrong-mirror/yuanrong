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
#include "httpserver/async_http_server.h"
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
        httpServer_ = std::make_shared<AsyncHttpServer>();
        libruntimeManager_ = &YR::Libruntime::LibruntimeManager::Instance();
    }

    void TearDown() override {
        if (libruntimeManager_ != nullptr) {
            libruntimeManager_->StopTokenRefresh();
        }
    }

private:
    std::shared_ptr<AsyncHttpServer> httpServer_;
    std::string ip_ = "127.0.0.1";
    unsigned short port_ = 12346;
    int threadNum = 8;
    YR::Libruntime::LibruntimeManager* libruntimeManager_;
    std::shared_ptr<LibruntimeConfig> librConfig_;
};

std::shared_ptr<LibruntimeConfig> ConstructLibruntimeConfig()
{
    std::shared_ptr<LibruntimeConfig> librtCfg = std::make_shared<LibruntimeConfig>();
    return librtCfg;
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
    if (httpServer_->StartServer(ip_, port_, threadNum)) {
        std::cout << "start http server success" << std::endl;
    } else {
        std::cout << "start http server failed" << std::endl;
    }
    auto librtCfg = ConstructLibruntimeConfig();
    librtCfg->httpIocThreadsNum = 5;
    librtCfg->iamAddress = "http://127.0.0.1:12346";
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
