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

#include "src/utility/metrics/api/include/processor_actor.h"
#include "src/utility/metrics/common/include/transfer.h"

namespace observability {
namespace metrics {

ProcessorActor::~ProcessorActor()
{
    Finalize();
}

void ProcessorActor::SetExportMode(const ExporterOptions &options)
{
    if (options.mode == ExporterOptions::Mode::SIMPLE) {
        processMethod_ = &ProcessorActor::CollectOnceThenExport;
    } else {
        processMethod_ = &ProcessorActor::CollectAndStore;
        exportBatchSize_ = options.batchSize;
        StartBatchExportTimer(static_cast<int>(options.batchIntervalSec));
    }
}

void ProcessorActor::Finalize()
{
    for (const auto &timerInfo : collectTimerInfos_) {
        auto timer = timerInfo.second;
        if (timer) {
            YR::utility::CancelGlobalTimer(timer);
        }
    }

    if (batchExportTimer_) {
        YR::utility::CancelGlobalTimer(batchExportTimer_);
        batchExportTimer_ = nullptr;
    }
    collectTimerInfos_.clear();
    collectTimers_.clear();
}

void ProcessorActor::RegisterTimer(const int interval)
{
    auto it = collectTimers_.find(interval);
    if (it == collectTimers_.end()) {
        (void)collectTimers_.insert(interval);
        ReportData(interval);
    }
}

void ProcessorActor::RegisterCollectFunc(const std::function<CollectFunc> &collectFunc)
{
    collectFunc_ = collectFunc;
}

void ProcessorActor::RegisterExportFunc(const std::function<ExportFunc> &exportFunc)
{
    exportFunc_ = exportFunc;
}

void ProcessorActor::CollectOnceThenExport(const int interval)
{
    if (collectFunc_ == nullptr || exportFunc_ == nullptr) {
        return;
    }

    (void)exportFunc_(GetData(interval));
    if (interval > 0) {
        collectTimerInfos_[interval] = YR::utility::ExecuteByGlobalTimer(
            [this, interval]() {
                if (collectTimers_.count(interval) > 0) {
                    CollectOnceThenExport(interval);
                }
            },
            interval * SEC2MS,
            1);
    }
}

void ProcessorActor::ReportData(const int interval)
{
    if (processMethod_ != nullptr) {
        (this->*processMethod_)(interval);
    }
}

void ProcessorActor::StartBatchExportTimer(const int interval)
{
    (void)ExportAllData();
    batchExportTimer_ = YR::utility::ExecuteByGlobalTimer(
        [this, interval]() {
            StartBatchExportTimer(interval);
        },
        interval * SEC2MS,
        1);
}

void ProcessorActor::CollectAndStore(const int interval)
{
    if (collectFunc_ == nullptr) {
        return;
    }

    if (PutData(GetData(interval))) {
        (void)ExportAllData();
    }

    if (interval > 0) {
        collectTimerInfos_[interval] = YR::utility::ExecuteByGlobalTimer(
            [this, interval]() {
                if (collectTimers_.count(interval) > 0) {
                    CollectAndStore(interval);
                }
            },
            interval * SEC2MS,
            1);
    }
}

bool ProcessorActor::PutData(const std::vector<MetricsData> &data)
{
    (void)buffer_.insert(buffer_.end(), data.begin(), data.end());
    return buffer_.size() >= exportBatchSize_;
}

void ProcessorActor::ExportTemporarilyData(const std::shared_ptr<BasicMetric> &instrument)
{
    if (exportBatchSize_ == 0) {
        if (exportFunc_ != nullptr) {
            (void)exportFunc_(GetTemporarilyData(instrument));
        }
        return;
    }
    if (PutData(GetTemporarilyData(instrument))) {
        (void)ExportAllData();
    }
}

std::vector<MetricsData> ProcessorActor::GetTemporarilyData(const std::shared_ptr<BasicMetric> &instrument)
{
    std::vector<MetricsData> metricDataList;
    auto timestamp = instrument->GetTimestamp().time_since_epoch().count() == 0 ? std::chrono::system_clock::now()
                                                                                : instrument->GetTimestamp();
    MetricsData metricData = {
        .labels = instrument->GetLabels(),
        .name = instrument->GetName(),
        .description = instrument->GetDescription(),
        .unit = instrument->GetUnit(),
        .metricType = GetMetricTypeStr(instrument->GetMetricType()),
        .collectTimeStamp = timestamp,
        .metricValue = GetInstrumentValue(instrument)
    };
    metricDataList.push_back(metricData);
    return metricDataList;
}

std::vector<MetricsData> ProcessorActor::GetData(const int interval)
{
    if (collectFunc_ == nullptr) {
        return {};
    }
    return collectFunc_(std::chrono::system_clock::now(), interval);
}

bool ProcessorActor::ExportAllData()
{
    if (exportFunc_ != nullptr && !buffer_.empty()) {
        auto isOk = exportFunc_(buffer_);
        buffer_.clear();
        return isOk;
    }
    return true;
}

}  // namespace metrics
}  // namespace observability
