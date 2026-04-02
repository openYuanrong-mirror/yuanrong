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

#include "log_manager.h"

#ifdef __linux__
#include <sys/prctl.h>
#endif
#include <string>
#include <thread>

namespace YR {
namespace utility {
const std::string LOG_ROLLING_COMPRESS = "LOG_ROLLING_COMPRESS";

void LogManager::StartRollingCompress(const std::function<void(LogParam &)> &func)
{
    YRLOG_DEBUG("start log rolling compress process.");
    {
        std::unique_lock<std::mutex> l(mtx_);
        if (state_ == RUNNING) {
            YRLOG_INFO("log rolling compress is already running.");
            return;
        }
        state_ = RUNNING;
    }

    // Reduce the number of threads
    rollingCompressThread_ = std::thread(&LogManager::CronTask, this, func);
}

bool LogManager::AddLogParam(const std::string &rtCtx, LogParam logParam)
{
    std::unique_lock<std::mutex> l(mtx_);
    if (logParam.isLogMerge) {
        logParam.nodeName = DEFAULT_LOG_NAME;
        pid_t pid = getpid();
        logParam.modelName = std::to_string(pid);
        logParams_[rtCtx] = logParam;
        return true;
    }
    logParams_[rtCtx] = logParam;
    return true;
}

void LogManager::StopRollingCompress() noexcept
{
    {
        std::unique_lock<std::mutex> l(mtx_);
        if (state_ != RUNNING) {
            return;
        }
        state_ = STOPPED;
        rcCond_.notify_all();
    }
    if (rollingCompressThread_.joinable()) {
        rollingCompressThread_.join();
    }
    {
        std::unique_lock<std::mutex> l(mtx_);
        logParams_.clear();
    }
    YRLOG_DEBUG("stop log rolling compress complete.");
}

void LogManager::CronTask(const std::function<void(LogParam &)> &func)
{
#ifdef __linux__
    (void)prctl(PR_SET_NAME, LOG_ROLLING_COMPRESS.c_str());
#endif
    std::unique_lock<std::mutex> l(mtx_);
    while (state_ == RUNNING) {
        std::cv_status cs = rcCond_.wait_for(l, std::chrono::seconds(interval_));
        if (cs == std::cv_status::no_timeout) {
            YRLOG_DEBUG("thread wake up by app thread, do last log manage work and ready to exit.");
        }
        try {
            for (auto logParam : logParams_) {
                func(logParam.second);
            }
        } catch (std::exception &e) {
            YRLOG_WARN("cron task func error: {}", e.what());
        }
    }
}
}  // namespace utility
}  // namespace YR