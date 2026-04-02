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

#ifndef OBSERVABILITY_METRICS_CONSTANT_H
#define OBSERVABILITY_METRICS_CONSTANT_H

#include <cstdint>
#include <string>

namespace observability {
namespace metrics {

const uint16_t SEC2MS = 1000;
const uint32_t DEFAULT_EXPORT_BATCH_SIZE = 512;
const uint32_t DEFAULT_EXPORT_BATCH_INTERVAL_SEC = 15;

const std::string PROCESS_ACTOR_NAME = "processor_actor_for_metrics";

const uint8_t METRICS_NAME_MAX_SIZE = 63;
const uint8_t METRICS_UNIT_MAX_SIZE = 63;
const uint16_t METRICS_DESCRIPTION_MAX_SIZE = 512;
const std::string METRICS_CREATE_RULE =
    "Name: Maximum Length is 63 characters, first char should be alpha, subsequent chars should be either of "
    "alphabets, digits, underscore, minus, dot \n "
    "Unit: Maximum Length is 63 characters, all char should be ascii chars \n"
    "Description: Maximum Length is 512 characters.\n";

const std::string ALARM_LABEL_KEY = "yrAlarmLabelKey";
}  // namespace metrics
}  // namespace observability
#endif  // OBSERVABILITY_METRICS_CONSTANT_H
