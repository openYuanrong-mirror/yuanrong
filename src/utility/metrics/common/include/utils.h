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

#ifndef OBSERVABILITY_METRICS_UTILS_H
#define OBSERVABILITY_METRICS_UTILS_H

#include "metrics/sdk/metric_processor.h"
#include "src/utility/metrics/common/include/metric_logger.h"

namespace observability {
namespace metrics {

const uint32_t ONE_MONTH_IN_SECOND = 2592000;

namespace MetricsSdk = observability::sdk::metrics;

inline void ValidateExportConfigs(sdk::metrics::ExportConfigs &configs)
{
    if (configs.batchSize > MetricsSdk::DEFAULT_EXPORT_BATCH_SIZE || configs.batchSize < 1) {
        METRICS_LOG_WARN("{} configs.batchSize invalid, reset to {}", configs.batchSize,
                         MetricsSdk::DEFAULT_EXPORT_BATCH_SIZE);
        configs.batchSize = MetricsSdk::DEFAULT_EXPORT_BATCH_SIZE;
    }
    // batchIntervalSec [1s, 1month]
    if (configs.batchIntervalSec < 1 || configs.batchIntervalSec > ONE_MONTH_IN_SECOND) {
        METRICS_LOG_WARN("{} configs.batchIntervalSec invalid, reset to {}", configs.batchIntervalSec,
                         MetricsSdk::DEFAULT_EXPORT_BATCH_INTERVAL_SEC);
        configs.batchIntervalSec = MetricsSdk::DEFAULT_EXPORT_BATCH_INTERVAL_SEC;
    }
    if (configs.failureQueueMaxSize > MetricsSdk::DEFAULT_FAILURE_QUEUE_MAX_SIZE || configs.failureQueueMaxSize < 1) {
        METRICS_LOG_WARN("{} configs.failureQueueMaxSize invalid, reset to {}", configs.failureQueueMaxSize,
                         MetricsSdk::DEFAULT_FAILURE_QUEUE_MAX_SIZE);
        configs.failureQueueMaxSize = MetricsSdk::DEFAULT_FAILURE_QUEUE_MAX_SIZE;
    }
    if (configs.failureDataFileMaxCapacity > MetricsSdk::DEFAULT_FAILURE_FILE_MAX_CAPACITY ||
        configs.failureQueueMaxSize < 1) {
        METRICS_LOG_WARN("{} configs.failureDataFileMaxCapacity invalid, reset to {}",
                         configs.failureDataFileMaxCapacity, MetricsSdk::DEFAULT_FAILURE_FILE_MAX_CAPACITY);
        configs.failureDataFileMaxCapacity = MetricsSdk::DEFAULT_FAILURE_FILE_MAX_CAPACITY;
    }
}

inline void SerializeLabel(std::ostream &ost, const std::string &key,
                           const std::variant<int64_t, std::string, std::vector<std::string>> &value,
                           bool withComma = true)
{
    ost << R"(")" << key << R"(":)";
    std::visit([&ost](auto& val) {
        using T = std::decay_t<decltype(val)>;
        if constexpr (std::is_same_v<T, int64_t>) {
            ost << val;
        } else if constexpr (std::is_same_v<T, std::string>) {
            ost << R"(")" << val << R"(")";
        } else if constexpr (std::is_same_v<T, std::vector<std::string>>) {
            ost << "[";
            for (size_t i = 0; i < val.size(); ++i) {
                ost << (i != 0 ? ", " : "") << R"(")" << val[i] << R"(")";
            }
            ost << "]";
        }
    }, value);
    if (withComma) {
        ost << ",";
    }
}
}
}
#endif // OBSERVABILITY_METRICS_UTILS_H
