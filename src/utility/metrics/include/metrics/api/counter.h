/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2024-2024. All rights reserved.
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

#ifndef OBSERVABILITY_API_METRICS_COUNTER_H
#define OBSERVABILITY_API_METRICS_COUNTER_H

#include "metrics/api/metric_data.h"

namespace observability::api::metrics {

template <class T>
class Counter {
public:
    virtual ~Counter() = default;

    /**
     * @brief Set the counter by the given amount. The counter will not change if the given amount is negative.
     * @param val  the given amount
     */
    virtual void Set(const T val) noexcept = 0;

    /**
     * @brief Set the counter by the given amount & label. The counter will not change if the given amount is negative.
     * @param val  the given amount
     * @param labels the label assigned to the indicator
     */
    virtual void Set(const T val, const MetricLabels &labels) noexcept = 0;

    /**
     * @brief Set the counter. The counter will not change if the given amount is negative.
     * @param val  the given amount
     * @param labels the label assigned to the indicator
     * @param timestamp collection time of the indicator
     */
    virtual void Set(const T val, const MetricLabels &labels, const SystemTimeStamp &timestamp) noexcept = 0;

    /**
     * @brief Reset the counter to zero.
     */
    virtual void Reset() noexcept = 0;

    /**
     * @brief Increment the counter by the given amount. The counter will not change if the given amount is negative.
     * @param val  the given amount
     */
    virtual void Increment(const T &val) noexcept = 0;

    /**
     * @brief Get the current value of the counter.
     */
    virtual T GetValue() noexcept = 0;

    /**
     * @brief Get the current labels of the counter.
     */
    virtual const MetricLabels GetLabels() noexcept = 0;

    /**
     * @brief overloaded operator +=. Increment the counter by the given amount.
     * The counter will not change if the given amount is negative.
     * @param val  the given amount
     */
    virtual Counter &operator+=(const T &val) noexcept = 0;

    /**
     * @brief overloaded operator ++. Increment the counter by 1.
     */
    virtual Counter &operator++() noexcept = 0;
};

}  // namespace observability::api::metrics

#endif  // OBSERVABILITY_API_METRICS_COUNTER_H
