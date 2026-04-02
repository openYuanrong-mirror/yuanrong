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

#ifndef OBSERVABILITY_EXPORTERS_FILE_UTILS_H
#define OBSERVABILITY_EXPORTERS_FILE_UTILS_H

#include <cstdint>
#include <iostream>
#include <string>
#include <unistd.h>
#include <vector>

namespace observability::metrics::common {

void Glob(const std::string &pathPattern, std::vector<std::string> &paths);
void Read(FILE *f, uint8_t *buf, size_t *pSize);
int CompressFile(const std::string &src, const std::string &dest);
void DeleteFile(const std::string &filename);
void GetFileModifiedTime(const std::string &filename, int64_t &timestamp);
}  // observability:exporters::metrics

#endif  // OBSERVABILITY_EXPORTERS_FILE_UTILS_H
