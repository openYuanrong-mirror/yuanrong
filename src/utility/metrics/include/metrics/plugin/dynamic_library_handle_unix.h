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

#ifndef OBSERVABILITY_PLUGIN_METRICS_DYNAMIC_LOAD_HANDLE_UNIX_H
#define OBSERVABILITY_PLUGIN_METRICS_DYNAMIC_LOAD_HANDLE_UNIX_H

#include <dlfcn.h>
#include <unistd.h>
#include <iostream>

#include <climits>
#include <memory>

#include "metrics/plugin/dynamic_library_handle.h"
#include "metrics/plugin/hook.h"

namespace observability::plugin::metrics {

class DynamicLibraryHandleUnix final : public DynamicLibraryHandle {
public:
    explicit DynamicLibraryHandleUnix(void *handle) noexcept : handle_{ handle }
    {
    }

    ~DynamicLibraryHandleUnix() override
    {
        ::dlclose(handle_);
    }

private:
    void *handle_;
};

inline std::unique_ptr<Factory> LoadFactory(const char *plugin, std::string &error) noexcept
{
    if (access(plugin, F_OK) == -1) {
        CopyErrorMessage("Plugin not exist", error);
        return nullptr;
    }
    dlerror();

    auto handle = ::dlopen(plugin, RTLD_NOW | RTLD_LOCAL);
    if (handle == nullptr) {
        CopyErrorMessage(dlerror(), error);
        return nullptr;
    }

    std::shared_ptr<DynamicLibraryHandle> libraryHandle = std::make_shared<DynamicLibraryHandleUnix>(handle);
    if (libraryHandle == nullptr) {
        return nullptr;
    }

    auto makeFactoryImpl = reinterpret_cast<ObservabilityHook *>(::dlsym(handle, "ObservabilityMakeFactoryImpl"));
    if (makeFactoryImpl == nullptr) {
        CopyErrorMessage(dlerror(), error);
        return nullptr;
    }
    if (*makeFactoryImpl == nullptr) {
        CopyErrorMessage("Invalid plugin hook", error);
        return nullptr;
    }
    std::unique_ptr<char[]> pluginError;
    auto factoryImpl = (**makeFactoryImpl)(pluginError);
    if (factoryImpl == nullptr) {
        CopyErrorMessage(pluginError.get(), error);
        return nullptr;
    }
    return std::unique_ptr<Factory>{ new (std::nothrow) Factory{ std::move(libraryHandle), std::move(factoryImpl) } };
}

inline std::unique_ptr<observability::plugin::metrics::Factory> LoadFactoryFromLibrary(const std::string &libPath,
                                                                                       std::string &error)
{
    char realLibPath[PATH_MAX] = { 0 };
    if (realpath(libPath.c_str(), realLibPath) == nullptr) {
        CopyErrorMessage("failed to get real path of library", error);
        return nullptr;
    }
    auto factory = observability::plugin::metrics::LoadFactory(realLibPath, error);
    return factory;
}

inline std::shared_ptr<observability::exporters::metrics::Exporter> LoadExporterFromLibrary(const std::string &libPath,
                                                                                            const std::string &config,
                                                                                            std::string &error)
{
    auto factory = LoadFactoryFromLibrary(libPath, error);
    if (factory == nullptr) {
        std::cerr << "null factory: " << error << std::endl;
        return nullptr;
    }
    auto exporter = factory->MakeExporter(config, error);
    return exporter;
}

}  // namespace observability::plugin::metrics

#endif