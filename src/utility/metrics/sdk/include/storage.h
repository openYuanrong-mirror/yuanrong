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

#ifndef OBSERVABILITY_STORAGE_H
#define OBSERVABILITY_STORAGE_H

#include <functional>
#include <memory>
#include <mutex>
#include <vector>

#include "src/utility/metrics/api/include/basic_metric.h"
#include "src/utility/metrics/sdk/include/observer_result_t.h"

namespace observability {
namespace metrics {
using CallbackPtr = void (*)(observability::metrics::ObserveResult, MetricValue state);

struct AsyncCallbackRecord {
    std::shared_ptr<CallbackPtr> cb;
    std::shared_ptr<BasicMetric> instrument;
    MetricValue state;
};

class Storage {
public:
    /**
     * Register the metric with async way, the callback will be invoked when collect the metric from SDK.
     *
     * @param callbackPtr reference from callback , defined by user.
     * @param state value which user defined for setting the metric value later.
     * @param instrument the metric, gauge or counter ..
     * @param interval the collect time interval.
     */
    void AddMetricAsync(CallbackPtr callbackPtr, const MetricValue &state,
                        const std::shared_ptr<BasicMetric> &instrument,
                        const int interval);

    /**
     * Register the metric with sync way.
     *
     * @param instrument the metric, gauge or counter ..
     * @param interval the collect time interval.
     */
    void AddMetric(const std::shared_ptr<BasicMetric> &instrument, const int interval);

    /**
     * Collect the metrics from SDK.
     *
     * @param collectTime the timestamp fro collecting.
     * @param interval the collect time interval.
     * @return return the list of metrics data, which can be transformed to other form.
     */
    std::vector<MetricsData> Collect(const std::chrono::system_clock::time_point &collectTime, const int interval);

private:
    void Observe(const int interval);

    template <typename T>
    void SetValueForInstrument(const std::shared_ptr<BasicMetric> &instrument, const T &value) const;

    std::map<int, std::vector<std::unique_ptr<AsyncCallbackRecord>>> callbackIntervalMap_;
    std::map<int, std::vector<std::shared_ptr<BasicMetric>>> collectIntervalMap_;
    std::mutex callbackMapMutex_;
    std::mutex mutex_;
};

}  // namespace metrics
}  // namespace observability

#endif  // OBSERVABILITY_STORAGE_H
