/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2023-2023. All rights reserved.
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

#include <memory>
#include <mutex>
#include "yr/api/config.h"
#include "yr/api/runtime.h"

// Ensure singleton instance is exported from shared library
#if defined(_WIN32) || defined(_WIN64)
    #define YR_RUNTIME_SINGLETON_EXPORT __declspec(dllexport)
#else
    #define YR_RUNTIME_SINGLETON_EXPORT __attribute__((visibility("default")))
#endif

namespace YR {
namespace internal {
class LocalModeRuntime;

struct RuntimeManager {
    YR_RUNTIME_SINGLETON_EXPORT static RuntimeManager &GetInstance();

    YR_RUNTIME_SINGLETON_EXPORT static void Cleanup();

    void Initialize(Config::Mode mode);

    // for test
    void Initialize(std::shared_ptr<YR::Runtime> runtime);

    void Stop();

    std::shared_ptr<YR::Runtime> GetRuntime()
    {
        return yrRuntime;
    }

    bool IsLocalMode() const
    {
        return this->mode_ == Config::Mode::LOCAL_MODE;
    }

    std::shared_ptr<LocalModeRuntime> GetLocalModeRuntime()
    {
        return localModeRuntime_;
    }

    ~RuntimeManager() = default;

protected:

    // Static pointer for singleton to avoid duplication when statically linked
    static std::unique_ptr<RuntimeManager> instance_;
    static std::mutex instanceMutex_;

    std::shared_ptr<YR::Runtime> yrRuntime;
    std::shared_ptr<LocalModeRuntime> localModeRuntime_;
    Config::Mode mode_;
};

bool IsLocalMode();
std::shared_ptr<YR::Runtime> GetRuntime();
std::shared_ptr<LocalModeRuntime> GetLocalModeRuntime();
}  // namespace internal
}  // namespace YR