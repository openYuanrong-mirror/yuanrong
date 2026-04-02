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

#ifndef OBSERVABILITY_PLUGIN_METRICS_EXPORTER_H
#define OBSERVABILITY_PLUGIN_METRICS_EXPORTER_H

#include <memory>
#include <iostream>

#include "exporter_handle.h"
#include "metrics/exporters/exporter.h"
namespace observability::plugin::metrics {
class DynamicLibraryHandle;

class Exporter : public observability::exporters::metrics::Exporter, public std::enable_shared_from_this<Exporter> {
public:
    Exporter(std::shared_ptr<DynamicLibraryHandle> libraryHandle,
             std::unique_ptr<ExporterHandle> &&exporterHandle) noexcept
        : libraryHandle_{ std::move(libraryHandle) }, exporterHandle_{ std::move(exporterHandle) }
    {
    }

    observability::exporters::metrics::ExportResult Export(
        const std::vector<observability::sdk::metrics::MetricData> &data) noexcept override
    {
        return exporterHandle_->Exporter().Export(data);
    }

    observability::sdk::metrics::AggregationTemporality GetAggregationTemporality(
        observability::sdk::metrics::InstrumentType instrumentType) const noexcept override
    {
        return exporterHandle_->Exporter().GetAggregationTemporality(instrumentType);
    }

    void RegisterOnHealthChangeCb(const std::function<void(bool)> &onChange) noexcept override
    {
        exporterHandle_->Exporter().RegisterOnHealthChangeCb(onChange);
    }

    bool ForceFlush(std::chrono::microseconds timeout = (std::chrono::microseconds::max)()) noexcept override
    {
        return exporterHandle_->Exporter().ForceFlush(timeout);
    }

    bool Shutdown(std::chrono::microseconds timeout = std::chrono::microseconds(0)) noexcept override
    {
        return exporterHandle_->Exporter().Shutdown(timeout);
    }

    ~Exporter() override = default;

private:
    std::shared_ptr<DynamicLibraryHandle> libraryHandle_;
    std::unique_ptr<ExporterHandle> exporterHandle_;
};
}  // namespace observability::plugin::metrics
#endif