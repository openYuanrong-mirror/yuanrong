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

#pragma once

#include <list>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>

#include "src/utility/logger/logger.h"

namespace YR {
namespace Libruntime {

template <typename Key, typename Value>
class LRUCache {
public:
    explicit LRUCache(size_t cap) : capacity_(cap)
    {
        if (capacity_ == 0) {
            capacity_ = DEFAULT_CAPACITY;
            YRLOG_ERROR("Invalid LRUCache capacity {}, using default capacity {}", cap, DEFAULT_CAPACITY);
        }
    }

    std::optional<Value> Get(const Key &key)
    {
        auto it = cacheMap_.find(key);
        if (it == cacheMap_.end()) {
            return std::nullopt;
        }

        const Value &value = it->second->second;
        recentList_.splice(recentList_.begin(), recentList_, it->second);
        return value;
    }

    void Insert(const Key &key, const Value &value)
    {
        auto it = cacheMap_.find(key);
        if (it != cacheMap_.end()) {
            it->second->second = value;
            recentList_.splice(recentList_.begin(), recentList_, it->second);
            return;
        }

        if (recentList_.size() >= capacity_) {
            auto last = recentList_.end();
            --last;
            cacheMap_.erase(last->first);
            recentList_.pop_back();
        }

        recentList_.emplace_front(key, value);
        cacheMap_[key] = recentList_.begin();
    }

    void Erase(const Key &key)
    {
        auto it = cacheMap_.find(key);
        if (it == cacheMap_.end()) {
            return;
        }
        recentList_.erase(it->second);
        cacheMap_.erase(it);
    }

    void Clear()
    {
        recentList_.clear();
        cacheMap_.clear();
    }

private:
    using ListIter = typename std::list<std::pair<Key, Value>>::iterator;
    std::unordered_map<Key, ListIter> cacheMap_;
    std::list<std::pair<Key, Value>> recentList_;
    size_t capacity_;
    static constexpr size_t DEFAULT_CAPACITY = 20;
};

}  // namespace Libruntime
}  // namespace YR
