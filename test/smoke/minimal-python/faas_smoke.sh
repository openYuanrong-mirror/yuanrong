#!/usr/bin/env bash
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

YR_RUNTIME="${YR_SMOKE_BASE_URL:-http://127.0.0.1:8888}"
TENANT_ID="${YR_SMOKE_TENANT:-0}"
NAMESPACE="${YR_SMOKE_NAMESPACE:-faaspy}"
FUNCTION_NAME="${YR_SMOKE_FUNCTION:-smokehandler}"
FULL_NAME="0@${NAMESPACE}@${FUNCTION_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FUNC_DIR="${SCRIPT_DIR}/faas"
TMP_JSON="$(mktemp /tmp/yr-minimal-faas.XXXXXX.json)"
TEXT_BODY="$(mktemp /tmp/yr-minimal-faas-text.XXXXXX.json)"
ENV_BODY="$(mktemp /tmp/yr-minimal-faas-env.XXXXXX.json)"
REPEAT_BODY="$(mktemp /tmp/yr-minimal-faas-repeat.XXXXXX.json)"
SMOKE_FAILED=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${YELLOW}[INFO]${NC} $1"; }
log_pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
log_fail() { echo -e "${RED}[FAIL]${NC} $1"; SMOKE_FAILED=1; }

cleanup() {
    curl -sS -X DELETE \
        -H "X-Tenant-Id: ${TENANT_ID}" \
        "${YR_RUNTIME}/admin/v1/functions/${FULL_NAME}?versionNumber=latest" >/dev/null 2>&1 || true
    rm -f "${TMP_JSON}" "${TEXT_BODY}" "${ENV_BODY}" "${REPEAT_BODY}"
}
trap cleanup EXIT

render_function_json() {
    python3 - "${TMP_JSON}" "${FULL_NAME}" "${FUNC_DIR}" <<'PY'
import json
import sys

output_path, full_name, code_path = sys.argv[1:4]
data = {
    "name": full_name,
    "runtime": "python3.9",
    "description": "minimal smoke test handler",
    "handler": "handler.handler",
    "kind": "faas",
    "cpu": 300,
    "memory": 128,
    "timeout": 60,
    "customResources": {},
    "environment": {},
    "extendedHandler": {},
    "extendedTimeout": {},
    "minInstance": "0",
    "maxInstance": "1",
    "concurrentNum": "1",
    "storageType": "local",
    "codePath": code_path,
}
with open(output_path, "w", encoding="utf-8") as stream:
    json.dump(data, stream, ensure_ascii=False, indent=2)
PY
}

render_payloads() {
    printf '{"text":"hello","mode":"text"}' > "${TEXT_BODY}"
    printf '{"command":"env"}' > "${ENV_BODY}"
    printf '{"command":"repeat"}' > "${REPEAT_BODY}"
}

echo "--- FaaS Smoke Results ---"

log_info "Preparing function metadata..."
render_function_json
render_payloads

log_info "Deploying function..."
RESP=$(curl -sS -X POST "${YR_RUNTIME}/admin/v1/functions" \
    -H "Content-Type: application/json" \
    -H "X-Tenant-Id: ${TENANT_ID}" \
    -d @"${TMP_JSON}" 2>&1) || {
    log_fail "function deployment (curl failed)"
    echo "Response: ${RESP}"
}

if echo "${RESP}" | grep -q '"function"'; then
    log_pass "function deployment"
else
    log_fail "function deployment"
    echo "Response: ${RESP}"
fi

sleep 5

log_info "Invoking with text payload..."
RESP=$(curl -sS -X POST "${YR_RUNTIME}/invocations/${TENANT_ID}/${NAMESPACE}/${FUNCTION_NAME}/" \
    -H "Content-Type: application/json" \
    --data-binary @"${TEXT_BODY}" 2>&1) || {
    log_fail "text invoke (curl failed)"
    echo "Response: ${RESP}"
}

if echo "${RESP}" | grep -q '"ok":[[:space:]]*true' && echo "${RESP}" | grep -q '"echo":[[:space:]]*"hello"'; then
    log_pass "text invoke"
else
    log_fail "text invoke"
    echo "Response: ${RESP}"
fi

log_info "Invoking with JSON payload..."
RESP=$(curl -sS -X POST "${YR_RUNTIME}/invocations/${TENANT_ID}/${NAMESPACE}/${FUNCTION_NAME}/" \
    -H "Content-Type: application/json" \
    -d '{"name":"yuanrong"}' 2>&1) || {
    log_fail "JSON invoke (curl failed)"
    echo "Response: ${RESP}"
}

if echo "${RESP}" | grep -q '"ok":[[:space:]]*true' && echo "${RESP}" | grep -q '"mode":[[:space:]]*"json"'; then
    log_pass "JSON invoke"
else
    log_fail "JSON invoke"
    echo "Response: ${RESP}"
fi

log_info "Checking environment variable..."
RESP=$(curl -sS -X POST "${YR_RUNTIME}/invocations/${TENANT_ID}/${NAMESPACE}/${FUNCTION_NAME}/" \
    -H "Content-Type: application/json" \
    --data-binary @"${ENV_BODY}" 2>&1) || {
    log_fail "env var check (curl failed)"
    echo "Response: ${RESP}"
}

if echo "${RESP}" | grep -q '"instance_id"' && echo "${RESP}" | grep -q '"function_name"'; then
    log_pass "env var visible"
else
    log_fail "env var not visible in response"
    echo "Response: ${RESP}"
fi

log_info "Testing repeated invoke..."
RESP1=$(curl -sS -X POST "${YR_RUNTIME}/invocations/${TENANT_ID}/${NAMESPACE}/${FUNCTION_NAME}/" \
    -H "Content-Type: application/json" \
    --data-binary @"${REPEAT_BODY}" 2>&1)
RESP2=$(curl -sS -X POST "${YR_RUNTIME}/invocations/${TENANT_ID}/${NAMESPACE}/${FUNCTION_NAME}/" \
    -H "Content-Type: application/json" \
    --data-binary @"${REPEAT_BODY}" 2>&1)

if echo "${RESP1}" | grep -q '"ok":[[:space:]]*true' && echo "${RESP2}" | grep -q '"ok":[[:space:]]*true'; then
    log_pass "repeated invoke"
else
    log_fail "repeated invoke failed"
    echo "Response1: ${RESP1}"
    echo "Response2: ${RESP2}"
fi

echo ""
if [ "${SMOKE_FAILED}" -eq 0 ]; then
    echo "--- FaaS Smoke: ALL PASS ---"
else
    echo "--- FaaS Smoke: SOME FAILURES ---"
fi

exit "${SMOKE_FAILED}"
