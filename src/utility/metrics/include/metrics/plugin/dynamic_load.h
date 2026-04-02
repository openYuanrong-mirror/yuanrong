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

#ifndef OBSERVABILITY_PLUGIN_METRICS_DYNAMIC_LOAD_H
#define OBSERVABILITY_PLUGIN_METRICS_DYNAMIC_LOAD_H

#include <dlfcn.h>

#include <memory>

#include "metrics/plugin/dynamic_library_handle_unix.h"

namespace observability::plugin::metrics {

class Factory;

std::unique_ptr<Factory> LoadFactory(const char *plugin, std::string &error) noexcept;
std::unique_ptr<observability::plugin::metrics::Factory> LoadFactoryFromLibrary(const std::string &libPath);

std::shared_ptr<observability::exporters::metrics::Exporter> LoadExporterFromLibrary(const std::string &libPath,
                                                                                     const std::string &config);
}  // namespace observability::plugin::metrics

#endif