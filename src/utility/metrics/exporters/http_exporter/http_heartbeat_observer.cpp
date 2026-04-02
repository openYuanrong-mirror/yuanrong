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

#include "src/utility/metrics/exporters/http_exporter/http_heartbeat_observer.h"

#include "src/utility/metrics/common/include/metric_logger.h"

namespace observability::exporters::metrics {

const int32_t CODE_OK = 200;

HttpHeartbeatObserver::HttpHeartbeatObserver(const HeartbeatParam &heartbeatParam)
    : pingCycleMs_(heartbeatParam.heartbeatInterval), url_(heartbeatParam.heartbeatUrl), method_(heartbeatParam.method)
{
    curlHelper_ = std::make_shared<CurlHelper>();
    if (curlHelper_) {
        curlHelper_->SetHttpHeader(heartbeatParam.httpHeader.c_str());
        curlHelper_->SetSSLConfig(heartbeatParam.sslConfig);
    }
}

HttpHeartbeatObserver::~HttpHeartbeatObserver()
{
    Stop();
}

void HttpHeartbeatObserver::RegisterOnHealthChangeCb(const std::function<void(bool)> &onChange)
{
    onChange_ = onChange;
}

void HttpHeartbeatObserver::Start()
{
    if (!healthy_.load() || url_.empty()) {
        METRICS_LOG_INFO("Can not start http heartbeat, health status is {}, url is {}", healthy_.load(), url_);
        return;
    }
    running_.store(true);
    Ping();
}

void HttpHeartbeatObserver::Stop()
{
    running_.store(false);
    if (timer_) {
        METRICS_LOG_INFO("heartbeat cancel send ping");
        YR::utility::CancelGlobalTimer(timer_);
        timer_ = nullptr;
    }
}

void HttpHeartbeatObserver::Ping()
{
    if (!running_.load()) {
        return;
    }

    std::ostringstream oss;
    auto responseCode = curlHelper_->SendRequest(method_, url_, oss);
    if (responseCode != CODE_OK) {
        METRICS_LOG_WARN("metrics export backend health check res is {}", responseCode);
        healthy_.store(false);
        if (onChange_ != nullptr) {
            onChange_(false);
        }
        ScheduleNextPing();
    } else {
        METRICS_LOG_INFO("metrics export backend health check finishes, exporter is healthy");
        healthy_.store(true);
        if (onChange_ != nullptr) {
            onChange_(true);
        }
        Stop();
    }
}

void HttpHeartbeatObserver::ScheduleNextPing()
{
    if (!running_.load()) {
        return;
    }

    timer_ = YR::utility::ExecuteByGlobalTimer(
        [this]() {
            Ping();
        },
        pingCycleMs_,
        -1
    );
}
}
