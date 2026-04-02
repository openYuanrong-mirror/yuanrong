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

#include "gw_datasystem_client_wrapper.h"

#include "src/libruntime/gwclient/gw_client.h"
#include "src/utility/logger/logger.h"

namespace YR {
namespace Libruntime {

GwDatasystemClientWrapper::GwDatasystemClientWrapper(std::shared_ptr<GwClient> client)
{
    gwClient = client;
}

ErrorInfo GwDatasystemClientWrapper::GDecreaseRef(const std::vector<std::string> &objectIds,
                                                   std::vector<std::string> &failedObjectIds)
{
    if (auto locked = gwClient.lock()) {
        auto failedIdsPtr = std::make_shared<std::vector<std::string>>();
        auto err = locked->PosixGDecreaseRef(objectIds, failedIdsPtr);
        if (err.OK()) {
            failedObjectIds.assign(failedIdsPtr->begin(), failedIdsPtr->end());
            return ErrorInfo();
        } else {
            return err;
        }
    } else {
        YRLOG_DEBUG("gw client pointer is expired.");
        return ErrorInfo(ErrorCode::ERR_INNER_SYSTEM_ERROR, "gw client pointer is expired");
    }
}

void GwDatasystemClientWrapper::SetTenantId(const std::string &tenantId)
{
    if (auto locked = gwClient.lock()) {
        locked->SetTenantId(tenantId);
    }
}

}  // namespace Libruntime
}  // namespace YR
