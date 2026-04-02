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

#ifndef OBSERVABILITY_METER_H
#define OBSERVABILITY_METER_H

#include <memory>

#include "src/utility/metrics/api/include/gauge.h"
#include "src/utility/metrics/api/include/processor_actor.h"
#include "src/utility/metrics/common/include/validate.h"
#include "src/utility/metrics/sdk/include/storage.h"

namespace observability {
namespace metrics {

struct TitleOptions {
    std::string name;
    std::string description = "";
    std::string unit = "";
};

class Meter {
public:
    Meter(const std::shared_ptr<Storage> &storage, const std::shared_ptr<ProcessorActor> &processorActor,
          const bool enableMetrics = true)
        : storage_(storage), processorActor_(processorActor), enableMetrics_(enableMetrics)
    {
    }
    ~Meter() = default;

    /**
     * @brief Create a periodic gauge, the metric which can be increased or decreased
     * @param titleOptions  The metric name/description/unit
     * @param interval Collect  period interval, default 0: report once，optional
     * @param callback The value of metric is obtained from the callback result when collected，optional
     * @param refState Reference state that can be transferred in the callback, optional
     */
    template <typename T>
    std::shared_ptr<Gauge<T>> CreateGauge(const TitleOptions &title, const uint32_t interval = 0,
                                          const CallbackPtr &callback = nullptr,
                                          const MetricValue &refState = MetricValue())
    {
        if (!enableMetrics_) {
            return std::make_shared<EmptyGauge<T>>();
        }

        if (!ValidateMetric(title.name, title.description, title.unit)) {
            std::cerr << "<Meter> Create Gauge Failed: Invalid parameters \n" + METRICS_CREATE_RULE << std::endl;
            return nullptr;
        }

        auto metric = std::make_shared<Gauge<T>>(title.name, title.description, title.unit);
        // interval equal to 0, means data just collect once, need user call collect
        if (interval == 0) {
            return metric;
        }

        // interval greater than 0, means data need collect period, need create timer automatically report
        if (processorActor_) {
            processorActor_->RegisterTimer(interval);
        }
        if (callback == nullptr) {
            storage_->AddMetric(metric, interval);
        } else {
            storage_->AddMetricAsync(callback, refState, metric, interval);
        }
        return metric;
    }

    /**
     * @brief Collect Temporarily Metric
     * @param metric the collect metric
     */
    template <typename T>
    void Collect(const std::shared_ptr<T> &metric)
    {
        if (!enableMetrics_) {
            return;
        }

        if (processorActor_) {
            processorActor_->ExportTemporarilyData(std::static_pointer_cast<BasicMetric>(metric));
        }
    }

private:
    std::shared_ptr<Storage> storage_;
    std::shared_ptr<ProcessorActor> processorActor_;
    bool enableMetrics_ = true;
};

}  // namespace metrics
}  // namespace observability
#endif  // OBSERVABILITY_METER_H
