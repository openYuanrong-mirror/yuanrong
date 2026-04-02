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

#include "src/utility/metrics/sdk/include/meter_provider.h"

#include <memory>

#include "src/utility/metrics/common/include/exporter_loader.h"
#include "metrics/api/meter_provider.h"
#include "metrics/sdk/meter_context.h"
#include "metrics/sdk/meter_provider.h"

namespace MetricsApi = observability::api::metrics;

namespace observability {
namespace metrics {

MeterProvider::MeterProvider()
{
}

MeterProvider::~MeterProvider() noexcept
{
}

void MeterProvider::TerminateLitebus() const noexcept
{
    // Deprecated - no op
}

bool MeterProvider::Init(const MeterParam &param)
{
    enableMetrics_ = param.enableMetrics;

    if (!enableMetrics_) {
        meter_ = std::make_shared<Meter>(nullptr, nullptr, enableMetrics_);
        return false;
    }

    if (isInitialized_) {
        return true;
    }

    storage_ = std::make_shared<Storage>();
    processorActor_ = std::make_shared<ProcessorActor>();
    meter_ = std::make_shared<Meter>(storage_, processorActor_, enableMetrics_);

    isInitialized_ = true;
    return true;
}

void MeterProvider::Finalize()
{
    if (!isInitialized_ || !enableMetrics_) {
        isInitialized_ = false;
        return;
    }

    if (processorActor_ != nullptr) {
        // ProcessorActor destructor will handle cleanup
        processorActor_ = nullptr;
    }
    if (exporter_ != nullptr) {
        (void)exporter_->Finalize();
        exporter_ = nullptr;
    }

    isInitialized_ = false;
}

void MeterProvider::SetExporter(std::unique_ptr<BasicExporter> &exporter)
{
    if (!enableMetrics_) {
        std::cerr << "<MeterProvider> Warn: Failed to set exporter, Metrics is disabled." << std::endl;
        return;
    }

    if (!isInitialized_) {
        std::cerr
            << "<MeterProvider> Failed to set exporter: MeterProvider uninitialized, Init method must be called first."
            << std::endl;
        return;
    }

    if (exporter_ != nullptr) {
        std::cerr << "<MeterProvider> Failed to set exporter: The exporter cannot be set twice." << std::endl;
        return;
    }

    exporter_ = std::move(exporter);
    StartProcessorActor();
}

void MeterProvider::StartProcessorActor()
{
    processorActor_->RegisterExportFunc(std::bind(&BasicExporter::Export, exporter_.get(), std::placeholders::_1));
    processorActor_->RegisterCollectFunc(
        std::bind(&Storage::Collect, storage_.get(), std::placeholders::_1, std::placeholders::_2));
    processorActor_->SetExportMode(exporter_->GetExporterOptions());
}

std::shared_ptr<Meter> MeterProvider::GetMeter()
{
    return meter_;
}

}  // namespace metrics

namespace sdk {
namespace metrics {

MeterProvider::MeterProvider() noexcept : context_(std::make_shared<MeterContext>())
{
}

MeterProvider::~MeterProvider()
{
}

std::shared_ptr<MetricsApi::Meter> MeterProvider::GetMeter(const std::string &meterName) noexcept
{
    for (auto &meter : context_->GetMeters()) {
        if (meter->GetName() == meterName) {
            return meter;
        }
    }
    auto meter = std::make_shared<Meter>(context_, meterName);
    context_->AddMeter(meter);
    return meter;
}

void MeterProvider::AddMetricProcessor(const std::shared_ptr<MetricProcessor> &processor) noexcept
{
    context_->AddMetricProcessor(processor);
}

}  // namespace metrics
}  // namespace sdk
}  // namespace observability
