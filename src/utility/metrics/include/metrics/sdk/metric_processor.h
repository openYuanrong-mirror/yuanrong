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

#ifndef OBSERVABILITY_SDK_METRICS_METRIC_PROCESSOR_H
#define OBSERVABILITY_SDK_METRICS_METRIC_PROCESSOR_H

#include <unordered_set>

#include "metrics/sdk/instruments.h"
#include "metrics/sdk/meter_provider.h"
#include "metrics/sdk/metric_data.h"

namespace observability::sdk::metrics {

const uint32_t DEFAULT_EXPORT_BATCH_SIZE = 512;
const uint32_t DEFAULT_EXPORT_BATCH_INTERVAL_SEC = 15;
const uint32_t DEFAULT_FAILURE_QUEUE_MAX_SIZE = 1000;
const uint32_t SIZE_MEGA_BYTES = 1024 * 1024; // 1MB
const uint32_t DEFAULT_FAILURE_FILE_MAX_CAPACITY = 1024;  // MB
const uint32_t DEFAULT_HEARTBEAT_INTERVAL = 5000;  // ms

enum class ExportMode { IMMEDIATELY, BATCH };

struct ExportConfigs {
    std::string exporterName;
    ExportMode exportMode = ExportMode::BATCH;
    uint32_t batchSize = DEFAULT_EXPORT_BATCH_SIZE;
    uint32_t batchIntervalSec = DEFAULT_EXPORT_BATCH_INTERVAL_SEC;
    uint32_t failureQueueMaxSize = DEFAULT_FAILURE_QUEUE_MAX_SIZE;
    std::string failureDataDir = "/home/sn/metrics/failure";
    uint32_t failureDataFileMaxCapacity = DEFAULT_FAILURE_FILE_MAX_CAPACITY;  // MB
    std::unordered_set<std::string> enabledInstruments = {};
};

class MetricProcessor {
public:
    enum class ProcessorType { PUSH, PULL };

    virtual ~MetricProcessor() = default;

    virtual ProcessorType GetProcessorType() noexcept = 0;
    virtual AggregationTemporality GetAggregationTemporality(InstrumentType instrumentType) const noexcept = 0;
};

class MetricPushProcessor : public MetricProcessor {
public:
    ~MetricPushProcessor() override = default;
    virtual void Export(const MetricData &data) noexcept = 0;

    ProcessorType GetProcessorType() noexcept override;

private:
    const ProcessorType type_ = ProcessorType::PUSH;
};

class MetricPullProcessor : public MetricProcessor {
public:
    ~MetricPullProcessor() override = default;
    ProcessorType GetProcessorType() noexcept override;

private:
    const ProcessorType type_ = ProcessorType::PULL;
};

}  // namespace observability::sdk::metrics

#endif