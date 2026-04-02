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

#ifndef OBSERVABILITY_METER_PROVIDER_H
#define OBSERVABILITY_METER_PROVIDER_H

#include "src/utility/metrics/api/include/meter.h"
#include "src/utility/metrics/api/include/processor_actor.h"
#include "src/utility/metrics/sdk/include/storage.h"

namespace observability {
namespace metrics {

struct MeterParam {
    bool enableMetrics = true;
};

class MeterProvider {
public:
    MeterProvider(const MeterProvider &) = delete;
    MeterProvider(MeterProvider &&) = delete;
    MeterProvider &operator=(const MeterProvider &) = delete;
    MeterProvider &operator=(MeterProvider &&) = delete;

    /**
     * @brief Get a meter, the Meter can be used to create data such as Gauge and Counter.
     */
    std::shared_ptr<Meter> GetMeter();

    /**
     * @brief Initial meter provider
     * @param param MeterProvider initialization parameters
     */
    bool Init(const MeterParam &param = {});

    /**
     * @brief Finalize meter provider, used to stop data collection, export, and refresh.
     */
    void Finalize();

    /**
     * @brief Set Data Exporter, etc ostream, log and so on
     * @param exporter Exporter that implements BasicExporter
     */
    void SetExporter(std::unique_ptr<BasicExporter> &exporter);

    /**
     * @brief Get Instance, MeterProvider is a single case
     */
    static MeterProvider &GetInstance()
    {
        static MeterProvider meterProvider;
        return meterProvider;
    }

private:
    MeterProvider();
    ~MeterProvider() noexcept;
    void StartProcessorActor();
    void TerminateLitebus() const noexcept;

    std::unique_ptr<BasicExporter> exporter_{ nullptr };
    std::shared_ptr<Meter> meter_{ nullptr };
    std::shared_ptr<ProcessorActor> processorActor_{ nullptr };
    std::shared_ptr<Storage> storage_{ nullptr };
    std::atomic<bool> isInitialized_{ false };
    bool enableMetrics_{ true };
};
}  // namespace metrics
}  // namespace observability
#endif  // OBSERVABILITY_METER_PROVIDER_H
