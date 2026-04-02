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
#include "file_watcher.h"

#ifdef __APPLE__
#include <dispatch/dispatch.h>
#include <CoreServices/CoreServices.h>
#include <filesystem>

// macOS implementation using FSEvents
namespace YR {
namespace utility {

struct FileWatcher::Impl {
    FSEventStreamRef stream;
    dispatch_queue_t queue;
    Callback callback;
    std::string filename;
    std::string watchedPath;
    std::atomic<bool> running;

    Impl(const std::string& fn, Callback cb)
        : stream(nullptr), queue(nullptr), callback(std::move(cb)), filename(fn),
          watchedPath(std::filesystem::path(fn).parent_path().string()), running(false) {}

    static void FSEventCallback(ConstFSEventStreamRef streamRef,
                                 void* clientCallBackInfo,
                                 size_t numEvents,
                                 void* eventPaths,
                                 const FSEventStreamEventFlags eventFlags[],
                                 const FSEventStreamEventId eventIds[]) {
        auto* impl = static_cast<Impl*>(clientCallBackInfo);
        auto targetPath = std::filesystem::path(impl->filename).lexically_normal();
        for (size_t i = 0; i < numEvents; ++i) {
            if (eventFlags[i] & (kFSEventStreamEventFlagItemModified |
                                 kFSEventStreamEventFlagItemCreated |
                                 kFSEventStreamEventFlagItemRenamed)) {
                const char* const* changedPaths = static_cast<const char* const*>(eventPaths);
                auto changedPath = std::filesystem::path(changedPaths[i]).lexically_normal();
                if (changedPath == targetPath) {
                    impl->callback(impl->filename);
                }
            }
        }
    }
};

FileWatcher::FileWatcher(const std::string &filename, Callback callback)
    : impl_(nullptr), filename_(filename), callback_(std::move(callback)), running_(false)
{
}

FileWatcher::~FileWatcher()
{
    Stop();
}

void FileWatcher::Start()
{
    if (running_) {
        return;
    }

    running_ = true;
    impl_ = new Impl(filename_, callback_);

    std::string pathToWatch = impl_->watchedPath.empty() ? "." : impl_->watchedPath;
    CFStringRef path = CFStringCreateWithCString(nullptr, pathToWatch.c_str(), kCFStringEncodingUTF8);
    CFArrayRef pathsToWatch = CFArrayCreate(nullptr, (const void**)&path, 1, nullptr);

    FSEventStreamContext context = {0};
    context.info = impl_;

    impl_->stream = FSEventStreamCreate(nullptr,
                                        Impl::FSEventCallback,
                                        &context,
                                        pathsToWatch,
                                        kFSEventStreamEventIdSinceNow,
                                        1.0,
                                        kFSEventStreamCreateFlagFileEvents);

    CFRelease(pathsToWatch);
    CFRelease(path);

    impl_->queue = dispatch_queue_create("com.yuanrong.fswatcher", nullptr);
    FSEventStreamSetDispatchQueue(impl_->stream, impl_->queue);
    FSEventStreamStart(impl_->stream);
}

void FileWatcher::Stop()
{
    if (!running_) {
        return;
    }
    running_ = false;

    if (impl_ && impl_->stream) {
        FSEventStreamStop(impl_->stream);
        FSEventStreamInvalidate(impl_->stream);
        FSEventStreamRelease(impl_->stream);
    }

    if (impl_ && impl_->queue) {
        dispatch_release(impl_->queue);
    }

    delete impl_;
    impl_ = nullptr;
}

void FileWatcher::Watch()
{
    // macOS implementation uses FSEvents, no polling needed
    std::this_thread::sleep_for(std::chrono::seconds(1));
}

}  // namespace utility
}  // namespace YR

#else
// Linux implementation using inotify
namespace YR {
namespace utility {

FileWatcher::FileWatcher(const std::string &filename, Callback callback)
    : fd_(-1), wd_(-1), filename_(filename), callback_(std::move(callback)), running_(false)
{
}

FileWatcher::~FileWatcher()
{
    Stop();
}

void FileWatcher::Start()
{
    if (running_) {
        return;
    }

    running_ = true;
    watcherThread_ = std::thread([this]() {
        while (true) {
            if (!running_) {
                break;
            }
            Watch();
            std::this_thread::sleep_for(std::chrono::seconds(1));
        }
    });
}

void FileWatcher::Stop()
{
    if (!running_) {
        return;
    }
    running_ = false;
    if (wd_ >= 0) {
        inotify_rm_watch(fd_, wd_);
        wd_ = -1;
    }
    if (fd_ >= 0) {
        close(fd_);
        fd_ = -1;
    }
    if (watcherThread_.joinable()) {
        watcherThread_.join();
    }
}

void FileWatcher::Watch()
{
    fd_ = inotify_init1(IN_NONBLOCK);
    if (fd_ < 0) {
        YRLOG_DEBUG("inotify_init1 failed {}", strerror(errno));
        return;
    }

    wd_ = inotify_add_watch(fd_, filename_.c_str(), WATCH_MASK);
    if (wd_ < 0) {
        YRLOG_DEBUG("inotify_add_watch failed {}", strerror(errno));
        close(fd_);
        fd_ = -1;
        return;
    }
    callback_(filename_);
    char buffer[EVENT_BUF_LEN];
    while (running_) {
        int length = read(fd_, buffer, EVENT_BUF_LEN);
        if (length < 0) {
            if (errno == EINTR) {  // Signal interrupted
                continue;
            }
            if (errno == EAGAIN) {  // No data available
                std::this_thread::sleep_for(std::chrono::seconds(1));
                continue;
            }
            YRLOG_WARN("read error: {}", strerror(errno));
            break;
        }

        int i = 0;
        while (i < length) {
            struct inotify_event *event = static_cast<struct inotify_event *>(static_cast<void *>(&buffer[i]));
            if (event->mask & IN_CLOSE_WRITE) {
                callback_(filename_);
            }
            i += sizeof(struct inotify_event) + event->len;
        }
    }
}
}  // namespace utility
}  // namespace YR
#endif
