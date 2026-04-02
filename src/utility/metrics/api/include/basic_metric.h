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

#ifndef OBSERVABILITY_BASIC_METRIC_H
#define OBSERVABILITY_BASIC_METRIC_H
#include <chrono>
#include <map>
#include <mutex>

namespace observability {
namespace metrics {
using LabelsType = std::map<std::string, std::string>;
enum class ValueType {
    INT = 0,
    UINT,
    DOUBLE,
    UNKNOWN,
};

enum class MetricType {
    COUNTER = 0,
    GAUGE,
    SUMMARY,
    HISTOGRAM,
};

inline ValueType GetMetricValueType(const std::string &typeName)
{
    char t = typeName.at(0);
    switch (t) {
        case 'i':
            return ValueType::INT;
        case 'l':
            return ValueType::INT;
        case 'm':
            return ValueType::UINT;
        case 'd':
            return ValueType::DOUBLE;
        default:
            return ValueType::UNKNOWN;
    }
}

class BasicMetric {
public:
    BasicMetric(const std::string &name, const std::string &description, const std::string &unit,
                const MetricType &metricType)
        : metricType_(metricType), name_(name), description_(description), unit_(unit)
    {
    }

    virtual ~BasicMetric() = default;

    std::string GetName() const
    {
        return name_;
    }

    std::string GetDescription() const
    {
        return description_;
    }

    std::string GetUnit() const
    {
        return unit_;
    }

    MetricType GetMetricType() const
    {
        return metricType_;
    }

    ValueType GetValueType() const
    {
        return valueType_;
    }

    virtual void SetTimestamp(const std::chrono::system_clock::time_point &timestamp)
    {
        std::lock_guard<std::mutex> lock{ mutex_ };
        timestamp_ = timestamp;
    }

    virtual std::chrono::system_clock::time_point GetTimestamp()
    {
        std::lock_guard<std::mutex> lock{ mutex_ };
        return timestamp_;
    }

    virtual std::map<std::string, std::string> GetLabels()
    {
        std::lock_guard<std::mutex> lock{ mutex_ };
        return labels_;
    }

    virtual void SetLabels(const LabelsType &labels)
    {
        std::lock_guard<std::mutex> lock{ mutex_ };
        labels_ = labels;
    }

    virtual void AddLabel(const std::string &key, const std::string &value)
    {
        std::lock_guard<std::mutex> lock{ mutex_ };
        labels_[key] = value;
    }

    virtual void DelLabelByKey(const std::string &key)
    {
        std::lock_guard<std::mutex> lock{ mutex_ };
        labels_.erase(key);
    }

protected:
    ValueType valueType_ = ValueType::UNKNOWN;
    std::mutex mutex_;

private:
    MetricType metricType_;
    std::string name_;
    std::string description_;
    std::string unit_;
    std::chrono::system_clock::time_point timestamp_;
    LabelsType labels_;
};
}  // namespace metrics
}  // namespace observability
#endif  // OBSERVABILITY_BASIC_METRIC_H
