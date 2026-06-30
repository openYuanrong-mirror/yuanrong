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

#ifdef ENABLE_DATASYSTEM

#include <memory>

#include "datasystem/object_client.h"

#include "datasystem_client_wrapper.h"
#include "src/libruntime/utils/datasystem_utils.h"

namespace YR {
namespace Libruntime {
class DatasystemObjectClientWrapper : public DatasystemClientWrapper {
public:
    DatasystemObjectClientWrapper(std::shared_ptr<datasystem::ObjectClient> client)
    {
        dsClient = client;
    }

    ErrorInfo GDecreaseRef(const std::vector<std::string> &objectIds,
                           std::vector<std::string> &failedObjectIds) override
    {
        datasystem::Status status = dsClient->GDecreaseRef(objectIds, failedObjectIds);
        if (!status.IsOk()) {
            return ErrorInfo(ConvertDatasystemErrorToCore(status.GetCode()), ModuleCode::DATASYSTEM, status.ToString());
        }
        return ErrorInfo();
    }

    void SetTenantId(const std::string &tenantId) override
    {
        (void)datasystem::Context::SetTenantId(tenantId);
    }

private:
    std::shared_ptr<datasystem::ObjectClient> dsClient;
};

}  // namespace Libruntime
}  // namespace YR

#endif  // ENABLE_DATASYSTEM