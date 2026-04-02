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

#ifndef OBSERVABILITY_PLUGIN_METRICS_FACTORY_H
#define OBSERVABILITY_PLUGIN_METRICS_FACTORY_H

#include <memory>
#include <string>

#include "metrics/plugin/exporter.h"
#include "metrics/plugin/utils.h"

namespace observability::plugin::metrics {

class Factory final {
public:
    class FactoryImpl {
    public:
        virtual ~FactoryImpl()
        {
        }

        virtual std::unique_ptr<ExporterHandle> MakeExporterHandle(std::string exporterConfig,
                                                                   std::unique_ptr<char[]> &error) const noexcept = 0;
    };

    Factory(std::shared_ptr<DynamicLibraryHandle> libraryHandle, std::unique_ptr<FactoryImpl> &&factoryImpl) noexcept
        : libraryHandle_{ std::move(libraryHandle) }, factoryImpl_{ std::move(factoryImpl) }
    {
    }

    std::shared_ptr<observability::exporters::metrics::Exporter> MakeExporter(std::string exporterConfig,
                                                                              std::string &error) const noexcept
    {
        (void)error;
        std::unique_ptr<char[]> pluginError;
        auto exporterHandle = factoryImpl_->MakeExporterHandle(exporterConfig, pluginError);
        if (exporterHandle == nullptr) {
            CopyErrorMessage(pluginError.get(), error);
            return nullptr;
        }

        return std::make_shared<Exporter>(libraryHandle_, std::move(exporterHandle));
    }

private:
    std::shared_ptr<DynamicLibraryHandle> libraryHandle_;
    std::unique_ptr<FactoryImpl> factoryImpl_;
};
}  // namespace observability::plugin::metrics

#endif