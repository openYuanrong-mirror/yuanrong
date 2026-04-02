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

#ifndef OBSERVABILITY_PLUGIN_METRICS_UTILS_H
#define OBSERVABILITY_PLUGIN_METRICS_UTILS_H
#include <string>

namespace observability::plugin::metrics {
inline void CopyErrorMessage(const char *source, std::string &destination) noexcept
try {
    if (source == nullptr) {
        return;
    }
    destination.assign(source);
} catch (const std::bad_alloc &) {
    // Failed to copy error message, no impact.
}
}  // namespace observability::plugin::metrics

#endif