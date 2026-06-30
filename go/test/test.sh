#!/bin/bash
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
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

set -e

CUR_DIR=$(dirname "$(readlink -f "$0")")
PROJECT_DIR=$(cd "${CUR_DIR}/.."; pwd)
CLIENT_DIR="${PROJECT_DIR}/pkg/dashboard/client"
YR_DATASYSTEM_DIR="${PROJECT_DIR}/../datasystem"
DATA_SYSTEM_CACHE=${DATA_SYSTEM_CACHE:-"https://build-logs.openeuler.openatom.cn:38080/temp-archived/openeuler/"\
"openYuanrong/yr_cache/$(uname -m)/yr-datasystem.tar.gz"}

function prepare_datasystem_go_sdk() {
    local ds_output_dir="${YR_DATASYSTEM_DIR}/output"
    if [ -f "${ds_output_dir}/sdk/go/go.mod" ]; then
        return
    fi

    mkdir -p "${ds_output_dir}"
    if ls "${ds_output_dir}"/yr-datasystem-*.tar.gz 1>/dev/null 2>&1; then
        tar --no-same-owner -zxf "${ds_output_dir}"/yr-datasystem-*.tar.gz --strip-components=1 -C "${ds_output_dir}"
    else
        echo "start to download datasystem"
        pushd "${ds_output_dir}"
        wget -O datasystem.tar.gz "${DATA_SYSTEM_CACHE}"
        tar --no-same-owner -zxf datasystem.tar.gz --strip-components=1
        popd
    fi
}

# go module prepare
export GO111MODULE=on
export GONOSUMDB=*
export CGO_ENABLED=1
prepare_datasystem_go_sdk
if [[ "$OSTYPE" == "darwin"* ]]; then
    export DYLD_LIBRARY_PATH="${DYLD_LIBRARY_PATH}:${YR_DATASYSTEM_DIR}/output/sdk/go/lib"
else
    export LD_LIBRARY_PATH="${LD_LIBRARY_PATH}:${YR_DATASYSTEM_DIR}/output/sdk/go/lib"
fi
go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.6
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.5.1
go install github.com/axw/gocov/gocov@latest
go install github.com/matm/gocov-html/cmd/gocov-html@latest

# resolve missing go.sum entry
# go env -w "GOFLAGS"="-mod=mod"

# coverage mode
# set: 每个语句是否执行？
# count: 每个语句执行了几次？
# atomic: 类似于count, 但表示的是并行程序中的精确计数
export GOCOVER_MODE="set"

# protoc
echo "generating fs proto pb objects"
. "${PROJECT_DIR}/build/faas/compile_functions.sh"

# dashboard test
sh "${CUR_DIR}/dashboard/test.sh"

# dashboard client test
cd "${CLIENT_DIR}"
npm i
CLIENT_CONFIG_DIR="${CLIENT_DIR}/src/config"
rm -f "${CLIENT_CONFIG_DIR}/config.json"
cp "${CLIENT_CONFIG_DIR}/config.json.bak" "${CLIENT_CONFIG_DIR}/config.json"
npm run coverage

# collector test
sh "${CUR_DIR}/collector/test.sh"

# common test
sh "${CUR_DIR}/common/test.sh"

# faasmanager test
sh "${CUR_DIR}/faasmanager/test.sh"

# faasscheduler test
sh "${CUR_DIR}/faasscheduler/test.sh"

echo "faas llt compile complete!!"
