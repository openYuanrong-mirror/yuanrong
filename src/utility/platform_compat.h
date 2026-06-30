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

#include <pthread.h>

#ifdef __APPLE__
inline int YR_SET_THREAD_NAME_CURRENT(const char *name)
{
    return pthread_setname_np(name);
}

inline int YR_SET_THREAD_NAME(pthread_t handle, const char *name)
{
    (void)handle;
    (void)name;
    return 0;
}
#else
inline int YR_SET_THREAD_NAME_CURRENT(const char *name)
{
    return pthread_setname_np(pthread_self(), name);
}

inline int YR_SET_THREAD_NAME(pthread_t handle, const char *name)
{
    return pthread_setname_np(handle, name);
}
#endif
