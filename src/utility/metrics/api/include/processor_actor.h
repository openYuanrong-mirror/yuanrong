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

#ifndef OBSERVABILITY_PROCESSOR_ACTOR_H
#define OBSERVABILITY_PROCESSOR_ACTOR_H

#include <chrono>
#include <unordered_set>
#include <map>
#include <memory>
#include "src/utility/timer_worker.h"
#include "src/utility/metrics/api/include/basic_metric.h"
#include "src/utility/metrics/common/include/constant.h"
#include "src/utility/metrics/sdk/include/basic_exporter.h"

namespace observability {
namespace metrics {
using CollectFunc = const std::vector<MetricsData>(const std::chrono::system_clock::time_point &timeStamp,
                                                   const int interval);
using ExportFunc = bool(const std::vector<MetricsData> &data);

class ProcessorActor {
public:
    ProcessorActor() = default;
    ~ProcessorActor();
    void RegisterTimer(const int interval);
    void RegisterCollectFunc(const std::function<CollectFunc> &collectFunc);
    void RegisterExportFunc(const std::function<ExportFunc> &exportFunc);
    void SetExportMode(const ExporterOptions &options);
    void ReportData(const int interval);
    bool ExportAllData();
    void ExportTemporarilyData(const std::shared_ptr<BasicMetric> &instrument);

private:
    void Finalize();
    void StartBatchExportTimer(const int interval);
    void CollectAndStore(const int interval);
    void CollectOnceThenExport(const int interval);
    std::vector<MetricsData> GetData(const int interval);
    bool PutData(const std::vector<MetricsData> &data);
    std::vector<MetricsData> GetTemporarilyData(const std::shared_ptr<BasicMetric> &instrument);

    std::vector<MetricsData> buffer_;
    std::map<int, std::shared_ptr<YR::utility::Timer>> collectTimerInfos_;
    void (ProcessorActor::*processMethod_)(const int){ nullptr };
    std::function<CollectFunc> collectFunc_{ nullptr };
    std::function<ExportFunc> exportFunc_{ nullptr };
    std::shared_ptr<YR::utility::Timer> batchExportTimer_;
    uint32_t exportBatchSize_ = 0;
    std::unordered_set<int> collectTimers_;
};
}  // namespace metrics
}  // namespace observability
#endif  // OBSERVABILITY_PROCESSOR_ACTOR_H
