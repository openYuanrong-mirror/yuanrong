/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2023-2023. All rights reserved.
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

#include "mock/mock_datasystem_client.h"
#include "src/libruntime/libruntime.h"
#include "src/libruntime/statestore/datasystem_state_store.h"
#include "src/utility/logger/logger.h"

using namespace testing;
using namespace YR::Libruntime;
using namespace YR::utility;

namespace YR {
namespace test {
class KVStateStoreTest : public testing::Test {
public:
    KVStateStoreTest(){};
    ~KVStateStoreTest(){};
    void SetUp() override
    {
        Mkdir("/tmp/log");
        LogParam g_logParam = {
            .logLevel = "DEBUG",
            .logDir = "/tmp/log",
            .nodeName = "test-runtime",
            .modelName = "test",
            .maxSize = 100,
            .maxFiles = 1,
            .logFileWithTime = false,
            .logBufSecs = 30,
            .maxAsyncQueueSize = 1048510,
            .asyncThreadCount = 1,
            .alsoLog2Stderr = true,
        };
        InitLog(g_logParam);
        stateStore_ = std::make_shared<DSCacheStateStore>();
        stateStore_->Init("127.0.0.1", 11111);
        InitGlobalTimer();
    }
    void TearDown() override
    {
        CloseGlobalTimer();
        stateStore_.reset();
    }

    std::shared_ptr<DSCacheStateStore> stateStore_;
};

TEST_F(KVStateStoreTest, KVWriteReadDelExist)
{
    std::string key = "123";
    std::string key2 = "456";
    std::string value = "this is mock value.";

    // Write
    std::shared_ptr<Buffer> sbuf = std::make_shared<NativeBuffer>(value.size());
    sbuf->MemoryCopy(value.data(), value.size());
    YR::Libruntime::ExistenceOpt existence = ExistenceOpt::NONE;
    YR::Libruntime::WriteMode writeMode = WriteMode::NONE_L2_CACHE;
    YR::Libruntime::SetParam setParam = {
        .writeMode = writeMode,
        .ttlSecond = 10,
        .existence = existence,
    };
    ErrorInfo err = stateStore_->Write(key, sbuf, setParam);
    ASSERT_EQ(err.Code(), ErrorCode::ERR_OK);

    // Read
    SingleReadResult readResult = stateStore_->Read(key, -1);
    ASSERT_EQ(readResult.second.Code(), ErrorCode::ERR_OK);
    MultipleReadResult multiReadResult = stateStore_->Read({key, key}, 100, false);
    ASSERT_EQ(multiReadResult.second.Code(), ErrorCode::ERR_GET_OPERATION_FAILED);

    // Exist
    MultipleExistResult emptyExistResult = stateStore_->Exist({});
    ASSERT_EQ(emptyExistResult.second.Code(), ErrorCode::ERR_PARAM_INVALID);
    MultipleExistResult existResult = stateStore_->Exist({key, key2});
    ASSERT_EQ(existResult.second.Code(), ErrorCode::ERR_OK);

    // Del
    err = stateStore_->Del(key);
    ASSERT_EQ(err.Code(), ErrorCode::ERR_OK);
    MultipleDelResult mdResult = stateStore_->Del({key, key2});
    ASSERT_EQ(mdResult.second.Code(), ErrorCode::ERR_OK);
}

TEST(KVStateStoreInitTest, InitFromDsConnectOptionsMapsFieldsCorrectly)
{
    DSCacheStateStore stateStore;
    DsConnectOptions options;
    options.host = "10.0.0.8";
    options.port = 32001;
    options.connectTimeoutMs = 4321;
    options.token = "token-value";
    options.clientPublicKey = "client-public";
    options.clientPrivateKey = "client-private";
    options.serverPublicKey = "server-public";
    options.accessKey = "access-key";
    options.secretKey = "secret-key";
    options.tenantId = "tenant-a";
    options.enableCrossNodeConnection = true;

    ErrorInfo err = stateStore.Init(options);

    ASSERT_EQ(err.Code(), ErrorCode::ERR_OK);
    EXPECT_EQ(stateStore.connectOpts.host, options.host);
    EXPECT_EQ(stateStore.connectOpts.port, options.port);
    EXPECT_EQ(stateStore.connectOpts.connectTimeoutMs, options.connectTimeoutMs);
    EXPECT_EQ(stateStore.connectOpts.requestTimeoutMs, options.connectTimeoutMs);
    EXPECT_EQ(stateStore.connectOpts.token.GetValue(), options.token);
    EXPECT_EQ(stateStore.connectOpts.clientPublicKey, options.clientPublicKey);
    EXPECT_EQ(stateStore.connectOpts.clientPrivateKey.GetValue(), options.clientPrivateKey);
    EXPECT_EQ(stateStore.connectOpts.serverPublicKey, options.serverPublicKey);
    EXPECT_EQ(stateStore.connectOpts.accessKey, options.accessKey);
    EXPECT_EQ(stateStore.connectOpts.secretKey.GetValue(), options.secretKey);
    EXPECT_EQ(stateStore.connectOpts.tenantId, options.tenantId);
    EXPECT_TRUE(stateStore.connectOpts.enableCrossNodeConnection);
}
}  // namespace test
}  // namespace YR
