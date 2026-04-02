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

#ifndef ENABLE_DATASYSTEM

#include "sensitive_value.h"

#include <algorithm>

namespace YR {
namespace Libruntime {

SensitiveValue::SensitiveValue(const char *str)
{
    if (str != nullptr) {
        SetData(str, strlen(str));
    }
}

SensitiveValue::SensitiveValue(const std::string &str)
{
    SetData(str.c_str(), str.size());
}

SensitiveValue::SensitiveValue(const char *str, size_t size)
{
    SetData(str, size);
}

SensitiveValue::SensitiveValue(std::unique_ptr<char[]> data, size_t size)
    : data_(std::move(data)), size_(size)
{
}

SensitiveValue::SensitiveValue(SensitiveValue &&other) noexcept
    : data_(std::move(other.data_)), size_(other.size_)
{
    other.size_ = 0;
}

SensitiveValue::SensitiveValue(const SensitiveValue &other)
{
    if (other.data_ != nullptr && other.size_ > 0) {
        SetData(other.data_.get(), other.size_);
    }
}

SensitiveValue::~SensitiveValue()
{
    Clear();
}

SensitiveValue &SensitiveValue::operator=(const SensitiveValue &other)
{
    if (this != &other) {
        Clear();
        if (other.data_ != nullptr && other.size_ > 0) {
            SetData(other.data_.get(), other.size_);
        }
    }
    return *this;
}

SensitiveValue &SensitiveValue::operator=(SensitiveValue &&other) noexcept
{
    if (this != &other) {
        Clear();
        data_ = std::move(other.data_);
        size_ = other.size_;
        other.size_ = 0;
    }
    return *this;
}

SensitiveValue &SensitiveValue::operator=(const char *str)
{
    Clear();
    if (str != nullptr) {
        SetData(str, strlen(str));
    }
    return *this;
}

SensitiveValue &SensitiveValue::operator=(const std::string &str)
{
    Clear();
    SetData(str.c_str(), str.size());
    return *this;
}

bool SensitiveValue::operator==(const SensitiveValue &other) const
{
    if (size_ != other.size_) {
        return false;
    }
    if (data_ == nullptr && other.data_ == nullptr) {
        return true;
    }
    if (data_ == nullptr || other.data_ == nullptr) {
        return false;
    }
    return memcmp(data_.get(), other.data_.get(), size_) == 0;
}

bool SensitiveValue::Empty() const
{
    return data_ == nullptr || size_ == 0;
}

const char *SensitiveValue::GetData() const
{
    return data_.get();
}

size_t SensitiveValue::GetSize() const
{
    return size_;
}

bool SensitiveValue::MoveTo(std::unique_ptr<char[]> &outData, size_t &outSize)
{
    if (data_ == nullptr) {
        return false;
    }
    outData = std::move(data_);
    outSize = size_;
    size_ = 0;
    return true;
}

void SensitiveValue::Clear()
{
    if (data_ != nullptr && size_ > 0) {
        // Securely clear the memory before releasing
        volatile char *p = data_.get();
        for (size_t i = 0; i < size_; ++i) {
            p[i] = 0;
        }
    }
    data_.reset();
    size_ = 0;
}

void SensitiveValue::SetData(const char *str, size_t size)
{
    if (str == nullptr || size == 0) {
        return;
    }
    data_ = std::make_unique<char[]>(size + 1);
    memcpy(data_.get(), str, size);
    data_[size] = '\0';
    size_ = size;
}

}  // namespace Libruntime
}  // namespace YR

#endif  // ENABLE_DATASYSTEM
