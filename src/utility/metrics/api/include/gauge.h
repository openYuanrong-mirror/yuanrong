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

#ifndef OBSERVABILITY_GAUGE_H
#define OBSERVABILITY_GAUGE_H

#include <map>

#include "basic_metric.h"
#include "src/utility/metrics/common/include/atomic_calc.h"
namespace observability {
namespace metrics {

template <typename T>
class Gauge : public BasicMetric {
public:
    explicit Gauge(const std::string &name, const std::string &description = "", const std::string &unit = "")
        : BasicMetric(name, description, unit, MetricType::GAUGE)
    {
        valueType_ = GetMetricValueType(typeid(T).name());
    }

    ~Gauge() override = default;

    virtual void Set(const T &val)
    {
        std::lock_guard<std::mutex> lock{ mutex_ };
        value_ = val;
    }

    virtual void Increment(const T &val)
    {
        std::lock_guard<std::mutex> lock{ mutex_ };
        value_ += val;
    }

    virtual void Decrement(const T &val)
    {
        std::lock_guard<std::mutex> lock{ mutex_ };
        value_ -= val;
    }
    virtual const T Value()
    {
        std::lock_guard<std::mutex> lock{ mutex_ };
        return value_;
    }

    virtual Gauge &operator+=(const T &val)
    {
        std::lock_guard<std::mutex> lock{ mutex_ };
        value_ += val;
        return *this;
    }

    virtual Gauge &operator-=(const T &val)
    {
        std::lock_guard<std::mutex> lock{ mutex_ };
        value_ -= val;
        return *this;
    }

private:
    std::atomic<T> value_{ 0 };
};

template <typename T>
class EmptyGauge : public Gauge<T> {
public:
    EmptyGauge() : Gauge<T>(""){};
    ~EmptyGauge() override = default;

    void SetTimestamp(const std::chrono::system_clock::time_point &) override
    {
    }

    std::chrono::system_clock::time_point GetTimestamp() override
    {
        return {};
    }

    void SetLabels(const LabelsType &) override
    {
    }

    std::map<std::string, std::string> GetLabels() override
    {
        return {};
    }

    void AddLabel(const std::string &, const std::string &) override
    {
    }

    void DelLabelByKey(const std::string &) override
    {
    }

    void Set(const T &) override
    {
    }

    void Increment(const T &) override
    {
    }

    void Decrement(const T &) override
    {
    }

    const T Value() override
    {
        return T();
    }

    EmptyGauge &operator+=(const T &)
    {
        return *this;
    }

    EmptyGauge &operator-=(const T &)
    {
        return *this;
    }
};

}  // namespace metrics
}  // namespace observability
#endif  // OBSERVABILITY_GAUGE_H
