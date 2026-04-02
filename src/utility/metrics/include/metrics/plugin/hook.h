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

#ifndef OBSERVABILITY_PLUGIN_METRICS_HOOK_H
#define OBSERVABILITY_PLUGIN_METRICS_HOOK_H

#include <memory>

#include "metrics/plugin/factory.h"

#define OBSERVABILITY_DEFINE_PLUGIN_HOOK(X)                                                                          \
    extern "C" {                                                                                                     \
    __attribute((weak)) extern observability::plugin::metrics::ObservabilityHook const ObservabilityMakeFactoryImpl; \
                                                                                                                     \
    observability::plugin::metrics::ObservabilityHook const ObservabilityMakeFactoryImpl = X;                        \
    }  // extern "C"

namespace observability::plugin::metrics {
class FactoryImpl;
using ObservabilityHook = std::unique_ptr<Factory::FactoryImpl> (*)(std::unique_ptr<char[]> &error);
}  // namespace observability::plugin::metrics

#endif