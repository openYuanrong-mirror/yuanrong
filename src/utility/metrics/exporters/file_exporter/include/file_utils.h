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

#ifndef OBSERVABILITY_METRICS_FILE_UTILS_H
#define OBSERVABILITY_METRICS_FILE_UTILS_H

#include <unistd.h>

#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

namespace observability {

namespace metrics {

struct FileUnit {
    FileUnit(std::string name, size_t size) : name(std::move(name)), size(size)
    {
    }
    ~FileUnit() = default;

    // filename.
    std::string name;

    // file size.
    size_t size;
};

bool FileExist(const std::string &filename, int mode = F_OK);
void Glob(const std::string &pathPattern, std::vector<std::string> &paths);
void Read(FILE *f, uint8_t *buf, size_t *pSize);
int CompressFile(const std::string &src, const std::string &dest);
void DeleteFile(const std::string &filename);
void GetFileModifiedTime(const std::string &filename, int64_t &timestamp);

}  // namespace metrics
}  // namespace observability

#endif  // OBSERVABILITY_METRICS_FILE_UTILS_H
