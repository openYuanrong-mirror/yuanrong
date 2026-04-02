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
#ifndef OBSERVABILITY_METRICS_FILE_EXPORTER_H
#define OBSERVABILITY_METRICS_FILE_EXPORTER_H

#include "src/utility/metrics/exporters/file_exporter/include/json_parser.h"
#include "src/utility/metrics/exporters/file_exporter/include/metric_logger.h"
#include "src/utility/metrics/sdk/include/basic_exporter.h"
#include "src/utility/metrics/sdk/include/metrics_data.h"

namespace observability {
namespace metrics {

class FileExporter : public BasicExporter {
public:
    explicit FileExporter(const FileParam &fileParam);

    bool Export(const std::vector<MetricsData> &data) override;
    bool ForceFlush() override;
    bool Finalize() override;

private:
    void InitLogger(const FileParam &fileParam);
    void InitJsonParser();
    std::string MetricSerialize(const MetricsData &metrics);
    std::shared_ptr<MetricLogger> metricLogger;
    std::shared_ptr<JsonParser> jsonParser;
};

}  // namespace metrics
}  // namespace observability
#endif  // OBSERVABILITY_METRICS_FILE_EXPORTER_H
