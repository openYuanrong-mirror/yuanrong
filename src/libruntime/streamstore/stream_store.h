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

#include "src/libruntime/err_type.h"
#include "src/libruntime/statestore/state_store.h"
#include "src/libruntime/utils/sensitive_value.h"
#include "stream_producer_consumer.h"

namespace YR {
namespace Libruntime {
class StreamStore {
public:
    virtual ~StreamStore() = default;
    virtual ErrorInfo Init(const std::string &ip, int port) = 0;
    virtual ErrorInfo Init(const std::string &ip, int port, bool enableDsAuth, bool encryptEnable,
                           const std::string &runtimePublicKey, const SensitiveValue &runtimePrivateKey,
                           const std::string &dsPublicKey, const SensitiveValue &token,
                           const std::string &ak, const SensitiveValue &sk) = 0;
    virtual ErrorInfo Init(const DsConnectOptions &options) = 0;
    virtual ErrorInfo Init(const DsConnectOptions &options, std::shared_ptr<StateStore> dsStateStore) = 0;
    virtual ErrorInfo CreateStreamProducer(const std::string &streamName, std::shared_ptr<StreamProducer> &producer,
                                           ProducerConf producerConf = {}) = 0;
    virtual ErrorInfo CreateStreamConsumer(const std::string &streamName, const SubscriptionConfig &config,
                                           std::shared_ptr<StreamConsumer> &consumer, bool autoAck = false) = 0;
    virtual ErrorInfo DeleteStream(const std::string &streamName) = 0;
    virtual ErrorInfo QueryGlobalProducersNum(const std::string &streamName, uint64_t &gProducerNum) = 0;
    virtual ErrorInfo QueryGlobalConsumersNum(const std::string &streamName, uint64_t &gConsumerNum) = 0;
    virtual void Shutdown() = 0;
    virtual ErrorInfo UpdateToken(SensitiveValue token) = 0;
    virtual ErrorInfo UpdateAkSk(std::string ak, SensitiveValue sk) = 0;
};
}  // namespace Libruntime
}  // namespace YR