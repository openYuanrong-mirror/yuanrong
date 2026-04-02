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

#ifndef METRICS_EXPORTERS_COMMON_SENSITIVE_VALUE_H
#define METRICS_EXPORTERS_COMMON_SENSITIVE_VALUE_H

#include <cstring>
#include <iostream>
#include <memory>
#include <string>

namespace observability::exporters::metrics {
class SensitiveData {
public:
    SensitiveData() = default;
    explicit SensitiveData(const char *str);

    explicit SensitiveData(const std::string &str);

    SensitiveData(const char *str, size_t size);

    SensitiveData(std::unique_ptr<char[]> data, size_t size) : data_(std::move(data)), size_(size)
    {
    }

    SensitiveData(SensitiveData &&other) noexcept : data_(std::move(other.data_)), size_(other.size_)
    {
        other.size_ = 0;
    }

    SensitiveData(const SensitiveData &other);

    ~SensitiveData();

    SensitiveData &operator=(const SensitiveData &other);

    SensitiveData &operator=(SensitiveData &&other) noexcept;

    SensitiveData &operator=(const char *str);

    SensitiveData &operator=(const std::string &str);

    bool operator==(const SensitiveData &other) const;

    bool Empty() const;

    const char *GetData() const;

    size_t GetSize() const;

    bool MoveTo(std::unique_ptr<char[]> &outData, size_t &outSize);

    void Clear() noexcept;

private:
    void SetData(const char *str, size_t size);

    std::unique_ptr<char[]> data_ = nullptr;
    size_t size_ = 0;
};
}  // namespace observability::exporters::metrics
#endif  // METRICS_EXPORTERS_COMMON_SENSITIVE_VALUE_H