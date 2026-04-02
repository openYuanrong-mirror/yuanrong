/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
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
#include "metrics/exporters/common/ssl_config.h"

#include <json.hpp>

#include "metrics/exporters/common/sensitive_data.h"

namespace observability::exporters::metrics {
void SSLConfig::Parse(const std::string &config)
{
    try {
        auto configJson = nlohmann::json::parse(config);
        if (configJson.find("isSSLEnable") != configJson.end()) {
            isSSLEnable_ = configJson.at("isSSLEnable");
        }
        if (isSSLEnable_ && configJson.find("rootCertFile") != configJson.end()) {
            rootCertFile_ = configJson.at("rootCertFile");
        }
        if (isSSLEnable_ && configJson.find("certFile") != configJson.end()) {
            certFile_ = configJson.at("certFile");
        }
        if (isSSLEnable_ && configJson.find("keyFile") != configJson.end()) {
            keyFile_ = configJson.at("keyFile");
        }
        if (isSSLEnable_ && configJson.find("passphrase") != configJson.end()) {
            passphrase_ = configJson.at("passphrase");
        }
    } catch (std::exception &e) {
        std::cerr << "failed to parse PrometheusPushExportOptions" << std::endl;
    }
}
}  // namespace observability::exporters::metrics