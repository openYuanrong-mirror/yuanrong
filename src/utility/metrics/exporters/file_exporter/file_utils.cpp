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

#include "src/utility/metrics/exporters/file_exporter/include/file_utils.h"

#include <glob.h>
#include <zlib.h>

#include <cstring>
#include <sstream>

#include "src/utility/metrics/common/file/file_utils.h"

namespace observability {

namespace metrics {

inline std::string StrErr(int errNum)
{
    char errBuf[256];
    errBuf[0] = '\0';
#ifdef __APPLE__
    // macOS version of strerror_r returns int and takes char* as second arg
    strerror_r(errNum, errBuf, sizeof errBuf);
    return std::string(errBuf);
#else
    // GNU version returns char*
    return strerror_r(errNum, errBuf, sizeof errBuf);
#endif
}

bool FileExist(const std::string &filename, int mode)
{
    return access(filename.c_str(), mode) == 0;
}

void Glob(const std::string &pathPattern, std::vector<std::string> &paths)
{
    observability::metrics::common::Glob(pathPattern, paths);
}

void Read(FILE *f, uint8_t *buf, size_t *pSize)
{
    observability::metrics::common::Read(f, buf, pSize);
}

int CompressFile(const std::string &src, const std::string &dest)
{
    return observability::metrics::common::CompressFile(src, dest);
}

void DeleteFile(const std::string &filename)
{
    if (unlink(filename.c_str()) != 0) {
        std::cout << "failed to delete file " << filename << std::endl;
    }
}

void GetFileModifiedTime(const std::string &filename, int64_t &timestamp)
{
    observability::metrics::common::GetFileModifiedTime(filename, timestamp);
}

}  // namespace metrics

}  // namespace observability
