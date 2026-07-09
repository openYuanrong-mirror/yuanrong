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

#include "metrics/exporters/http_exporter/curl_helper.h"

#include "curl/curl.h"

#include <iostream>

#include "src/utility/metrics/common/include/metric_logger.h"

namespace observability::exporters::metrics {
const int HTTP_REQUEST_ERROR = -1;
const long TIMEOUT = 3L;

namespace {
std::string BuildUrlWithScheme(const std::string &url, const SSLConfig &sslConfig)
{
    if (url.find("://") != std::string::npos) {
        return url;
    }
    return std::string(sslConfig.isSSLEnable_ ? "https://" : "http://") + url;
}

void SetRequestBody(void *curl, const std::string &bodyString)
{
    if (!bodyString.empty()) {
        (void)curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, bodyString.size());
        (void)curl_easy_setopt(curl, CURLOPT_POSTFIELDS, bodyString.data());
        return;
    }
    (void)curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, 0L);
}

void SetRequestMethod(void *curl, HttpRequestMethod method)
{
    switch (method) {
        case HttpRequestMethod::POST:
            (void)curl_easy_setopt(curl, CURLOPT_POST, 1L);
            break;
        case HttpRequestMethod::PUT:
            (void)curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "PUT");
            break;
        case HttpRequestMethod::GET:
        case HttpRequestMethod::DELETE:
        default:
            break;
    }
}

void ApplySSLConfig(void *curl, const SSLConfig &sslConfig)
{
    if (!sslConfig.isSSLEnable_) {
        return;
    }
    (void)curl_easy_setopt(curl, CURLOPT_CAINFO, sslConfig.rootCertFile_.c_str());
    (void)curl_easy_setopt(curl, CURLOPT_SSLCERT, sslConfig.certFile_.c_str());
    (void)curl_easy_setopt(curl, CURLOPT_SSLKEY, sslConfig.keyFile_.c_str());
    (void)curl_easy_setopt(curl, CURLOPT_KEYPASSWD, sslConfig.passphrase_.GetData());
    (void)curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 2L);
}
}  // namespace

CurlHelper::CurlHelper()
{
    auto error = curl_global_init(CURL_GLOBAL_ALL);
    if (error) {
        METRICS_LOG_ERROR("CurlHelper failed to initialize global curl, error {}", static_cast<long>(error));
        std::cerr << "<PrometheusPushExporter> failed to initialize global curl, error=" << static_cast<long>(error)
                  << std::endl;
        return;
    }
    curl_ = curl_easy_init();
    if (!curl_) {
        curl_global_cleanup();
        METRICS_LOG_ERROR("CurlHelper failed to initialize easy curl");
        std::cerr << "<PrometheusPushExporter> failed to initialize easy curl!" << std::endl;
        return;
    }
    METRICS_LOG_INFO("CurlHelper initialized successfully");
}

CurlHelper::~CurlHelper()
{
    curl_slist_free_all(httpHeader_);

    curl_easy_cleanup(curl_);
    curl_global_cleanup();

    if (httpHeader_ != nullptr) {
        httpHeader_ = nullptr;
    }

    if (curl_ != nullptr) {
        curl_ = nullptr;
    }
}

long CurlHelper::SendRequest(HttpRequestMethod method, const std::string &url, const std::ostringstream &ossBody)
{
    if (!curl_) {
        METRICS_LOG_ERROR("CurlHelper send request skipped because curl handle is null, url {}, method {}", url,
                          static_cast<int>(method));
        return HTTP_REQUEST_ERROR;
    }
    std::lock_guard<std::mutex> l(mutex_);
    curl_easy_reset(curl_);
    std::string urlWithScheme = BuildUrlWithScheme(url, sslConfig_);

    (void)curl_easy_setopt(curl_, CURLOPT_URL, urlWithScheme.c_str());
    (void)curl_easy_setopt(curl_, CURLOPT_HTTPHEADER, httpHeader_);
    (void)curl_easy_setopt(curl_, CURLOPT_TIMEOUT, TIMEOUT);

    auto bodyString = ossBody.str();
    METRICS_LOG_INFO("CurlHelper send request, url {}, method {}, bodyBytes {}, sslEnabled {}, timeoutSec {}",
                     urlWithScheme, static_cast<int>(method), bodyString.size(), sslConfig_.isSSLEnable_, TIMEOUT);
    SetRequestBody(curl_, bodyString);
    SetRequestMethod(curl_, method);
    ApplySSLConfig(curl_, sslConfig_);

    auto curlError = curl_easy_perform(curl_);
    long responseCode = 0;
    (void)curl_easy_getinfo(curl_, CURLINFO_RESPONSE_CODE, &responseCode);
    if (curlError != CURLE_OK) {
        auto errMsg = curl_easy_strerror(curlError);
        METRICS_LOG_ERROR("CurlHelper send request failed, curlError {}, errMsg {}, responseCode {}, url {}, method {}",
                          static_cast<long>(curlError), errMsg, responseCode, urlWithScheme, static_cast<int>(method));
        std::cerr << "Curl error, error code: " << static_cast<long>(curlError) << ", errMsg: " << errMsg
                  << ", responseCode: " << responseCode << ", url: " << urlWithScheme << std::endl;
        return -static_cast<long>(curlError);
    }
    METRICS_LOG_INFO("CurlHelper send request finished, responseCode {}, url {}, method {}", responseCode,
                     urlWithScheme, static_cast<int>(method));
    return responseCode;
}

void CurlHelper::SetSSLConfig(const SSLConfig &sslConfig)
{
    sslConfig_ = sslConfig;
}

void CurlHelper::SetHttpHeader(const char header[])
{
    httpHeader_ = curl_slist_append(httpHeader_, header);
}

}  // namespace observability::exporters::metrics
