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

#pragma once
#include <sstream>
#include <string>
#include <unordered_map>
#include "src/libruntime/utils/hash_utils.h"
#include "src/libruntime/utils/sensitive_value.h"
#include "src/libruntime/utils/utils.h"
namespace YR {
namespace Libruntime {
const double TIMESTAMP_EXPIRE_DURATION_SECONDS = 60;
const std::string TRACE_ID_KEY_NEW = "X-Trace-Id";
const std::string AUTHORIZATION_KEY = "Authorization";
const std::string INSTANCE_CPU_KEY = "X-Instance-Cpu";
const std::string INSTANCE_MEMORY_KEY = "X-Instance-Memory";
const std::string TIMESTAMP_KEY = "X-Timestamp";
const std::string ACCESS_KEY = "X-Access-Key";

std::string HashToHex(const std::string &message);

std::string GenerateRequestDigest(const std::unordered_map<std::string, std::string> &headers, const std::string &body,
                                  const std::string &url);

void SignHttpRequest(const std::string &accessKey, const SensitiveValue &secretKey,
                     std::unordered_map<std::string, std::string> &headers, const std::string &body,
                     const std::string &url);

bool VerifyHttpRequest(const std::string &accessKey, const SensitiveValue &secretKey,
                       std::unordered_map<std::string, std::string> &headers, const std::string &body,
                       const std::string &url);
}  // namespace Libruntime
}  // namespace YR