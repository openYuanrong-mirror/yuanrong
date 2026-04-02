/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.
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

#pragma once

#ifdef ENABLE_DATASYSTEM
#include "datasystem/utils/sensitive_value.h"
namespace YR {
namespace Libruntime {
using SensitiveValue = datasystem::SensitiveValue;
}  // namespace Libruntime
}  // namespace YR
#else

#include <cstring>
#include <memory>
#include <string>

namespace YR {
namespace Libruntime {

/**
 * @brief A class to securely store sensitive string data.
 * The data is cleared from memory when the object is destroyed.
 */
class SensitiveValue {
public:
    SensitiveValue() = default;
    SensitiveValue(const char *str);
    SensitiveValue(const std::string &str);
    SensitiveValue(const char *str, size_t size);
    SensitiveValue(std::unique_ptr<char[]> data, size_t size);

    SensitiveValue(SensitiveValue &&other) noexcept;
    SensitiveValue(const SensitiveValue &other);
    ~SensitiveValue();

    SensitiveValue &operator=(const SensitiveValue &other);
    SensitiveValue &operator=(SensitiveValue &&other) noexcept;
    SensitiveValue &operator=(const char *str);
    SensitiveValue &operator=(const std::string &str);
    bool operator==(const SensitiveValue &other) const;

    bool Empty() const;
    const char *GetData() const;
    size_t GetSize() const;
    bool MoveTo(std::unique_ptr<char[]> &outData, size_t &outSize);
    void Clear();

private:
    void SetData(const char *str, size_t size);

    std::unique_ptr<char[]> data_ = nullptr;
    size_t size_ = 0;
};

}  // namespace Libruntime
}  // namespace YR

#endif  // ENABLE_DATASYSTEM
