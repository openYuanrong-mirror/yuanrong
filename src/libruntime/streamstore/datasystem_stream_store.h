/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.
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

#ifdef ENABLE_DATASYSTEM

#include <mutex>

#include "datasystem/stream_client.h"
#include "src/dto/stream_conf.h"
#include "src/libruntime/statestore/state_store.h"
#include "src/libruntime/utils/constants.h"
#include "src/utility/logger/logger.h"
#include "stream_store.h"

namespace YR {
namespace Libruntime {
class DatasystemStreamStore : public StreamStore {
public:
    ErrorInfo Init(const std::string &ip, int port) override;

    ErrorInfo Init(const std::string &ip, int port, bool enableDsAuth, bool encryptEnable,
                   const std::string &runtimePublicKey, const datasystem::SensitiveValue &runtimePrivateKey,
                   const std::string &dsPublicKey, const datasystem::SensitiveValue &token, const std::string &ak,
                   const datasystem::SensitiveValue &sk) override;

    ErrorInfo Init(const DsConnectOptions &options) override;

    ErrorInfo Init(const DsConnectOptions &options, std::shared_ptr<StateStore> dsStateStore) override;

    ErrorInfo CreateStreamProducer(const std::string &streamName, std::shared_ptr<StreamProducer> &producer,
                                   ProducerConf producerConf = {}) override;

    ErrorInfo CreateStreamConsumer(const std::string &streamName, const SubscriptionConfig &config,
                                   std::shared_ptr<StreamConsumer> &consumer, bool autoAck = false) override;

    ErrorInfo DeleteStream(const std::string &streamName) override;

    ErrorInfo QueryGlobalProducersNum(const std::string &streamName, uint64_t &gProducerNum) override;

    ErrorInfo QueryGlobalConsumersNum(const std::string &streamName, uint64_t &gConsumerNum) override;

    void Shutdown() override;

    ErrorInfo UpdateToken(datasystem::SensitiveValue token) override;

    ErrorInfo UpdateAkSk(std::string ak, datasystem::SensitiveValue sk) override;

private:
    void InitOnce(void);
    ErrorInfo DoInitOnce(void);

    std::pair<datasystem::ProducerConf, ErrorInfo> CheckAndBuildProducerConf(const ProducerConf &producerConf);

    bool isInit = false;
    std::mutex initMutex;
    std::once_flag initFlag;
    ErrorInfo initErr;
    bool isReady = false;
    std::shared_ptr<datasystem::StreamClient> streamClient;
    std::string ip;
    int port;
    bool enableDsAuth = false;
    bool encryptEnable = false;
    std::string runtimePublicKey;
    datasystem::SensitiveValue runtimePrivateKey;
    std::string dsPublicKey;
    std::string ak;
    datasystem::SensitiveValue sk;
    datasystem::SensitiveValue token;
    datasystem::ConnectOptions connectOpts;
    std::unordered_map<libruntime::SubscriptionType, datasystem::SubscriptionType> typeMap = {
        {libruntime::SubscriptionType::STREAM, datasystem::SubscriptionType::STREAM},
        {libruntime::SubscriptionType::KEY_PARTITIONS, datasystem::SubscriptionType::KEY_PARTITIONS},
        {libruntime::SubscriptionType::ROUND_ROBIN, datasystem::SubscriptionType::ROUND_ROBIN},
        {libruntime::SubscriptionType::UNKNOWN, datasystem::SubscriptionType::UNKNOWN}};
    std::unordered_map<std::string, datasystem::StreamMode> streamModeMap = {
        {std::string(MPMC), datasystem::StreamMode::MPMC},
        {std::string(MPSC), datasystem::StreamMode::MPSC},
        {std::string(SPSC), datasystem::StreamMode::SPSC}};
    std::shared_ptr<StateStore> dsStateStore;

    ErrorInfo EnsureInit(void);
};

#define STREAM_STORE_INIT_ONCE()  \
    do {                          \
        InitOnce();               \
        if (!initErr.OK()) {      \
            return initErr;       \
        }                         \
    } while (0)

}  // namespace Libruntime
}  // namespace YR

#else  // !ENABLE_DATASYSTEM

#include "src/libruntime/streamstore/stream_store.h"

namespace YR {
namespace Libruntime {

static const ErrorInfo STREAMSTORE_NOT_ENABLED_ERROR(
    ErrorCode::ERR_DATASYSTEM_FAILED, ModuleCode::DATASYSTEM,
    "StreamStore operations require ENABLE_DATASYSTEM to be enabled");

class DatasystemStreamStore : public StreamStore {
public:
    ErrorInfo Init(const std::string &ip, int port) override
    {
        (void)ip;
        (void)port;
        return STREAMSTORE_NOT_ENABLED_ERROR;
    }

    ErrorInfo Init(const std::string &ip, int port, bool enableDsAuth, bool encryptEnable,
                   const std::string &runtimePublicKey, const SensitiveValue &runtimePrivateKey,
                   const std::string &dsPublicKey, const SensitiveValue &token, const std::string &ak,
                   const SensitiveValue &sk) override
    {
        (void)ip;
        (void)port;
        (void)enableDsAuth;
        (void)encryptEnable;
        (void)runtimePublicKey;
        (void)runtimePrivateKey;
        (void)dsPublicKey;
        (void)token;
        (void)ak;
        (void)sk;
        return STREAMSTORE_NOT_ENABLED_ERROR;
    }

    ErrorInfo Init(const DsConnectOptions &options) override
    {
        (void)options;
        return STREAMSTORE_NOT_ENABLED_ERROR;
    }

    ErrorInfo Init(const DsConnectOptions &options, std::shared_ptr<StateStore> dsStateStore) override
    {
        (void)options;
        (void)dsStateStore;
        return STREAMSTORE_NOT_ENABLED_ERROR;
    }

    ErrorInfo CreateStreamProducer(const std::string &streamName, std::shared_ptr<StreamProducer> &producer,
                                   ProducerConf producerConf = {}) override
    {
        (void)streamName;
        (void)producer;
        (void)producerConf;
        return STREAMSTORE_NOT_ENABLED_ERROR;
    }

    ErrorInfo CreateStreamConsumer(const std::string &streamName, const SubscriptionConfig &config,
                                   std::shared_ptr<StreamConsumer> &consumer, bool autoAck = false) override
    {
        (void)streamName;
        (void)config;
        (void)consumer;
        (void)autoAck;
        return STREAMSTORE_NOT_ENABLED_ERROR;
    }

    ErrorInfo DeleteStream(const std::string &streamName) override
    {
        (void)streamName;
        return STREAMSTORE_NOT_ENABLED_ERROR;
    }

    ErrorInfo QueryGlobalProducersNum(const std::string &streamName, uint64_t &gProducerNum) override
    {
        (void)streamName;
        (void)gProducerNum;
        return STREAMSTORE_NOT_ENABLED_ERROR;
    }

    ErrorInfo QueryGlobalConsumersNum(const std::string &streamName, uint64_t &gConsumerNum) override
    {
        (void)streamName;
        (void)gConsumerNum;
        return STREAMSTORE_NOT_ENABLED_ERROR;
    }

    void Shutdown() override {}

    ErrorInfo UpdateToken(SensitiveValue token) override
    {
        (void)token;
        return STREAMSTORE_NOT_ENABLED_ERROR;
    }

    ErrorInfo UpdateAkSk(std::string ak, SensitiveValue sk) override
    {
        (void)ak;
        (void)sk;
        return STREAMSTORE_NOT_ENABLED_ERROR;
    }
};

}  // namespace Libruntime
}  // namespace YR

#endif  // ENABLE_DATASYSTEM
