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

#ifndef OBSERVABILITY_SDK_METRICS_BATCH_EXPORT_PROCESSOR_H
#define OBSERVABILITY_SDK_METRICS_BATCH_EXPORT_PROCESSOR_H

#include <memory>

#include "metrics/exporters/exporter.h"
#include "metrics/sdk/metric_processor.h"

namespace observability::sdk::metrics {
class ProcessorActor;

class BatchExportProcessor : public MetricPushProcessor {
public:
    BatchExportProcessor(std::shared_ptr<observability::exporters::metrics::Exporter> &&exporter,
                         ExportConfigs &exportConfigs);
    ~BatchExportProcessor() override;

    AggregationTemporality GetAggregationTemporality(
        sdk::metrics::InstrumentType instrumentType) const noexcept override;

    void Export(const MetricData &data) noexcept override;

private:
    std::shared_ptr<ProcessorActor> processorActor_;
};

}  // namespace observability::sdk::metrics

#endif
