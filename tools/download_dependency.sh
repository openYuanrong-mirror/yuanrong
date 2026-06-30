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

BASE_DIR=$(
    cd "$(dirname "$0")"
    pwd
)
RUNTIME_SRC_DIR="${BASE_DIR}/../"
YR_DATASYSTEM_BIN_DIR="${RUNTIME_SRC_DIR}/datasystem"
YR_FUNCTIONSYSTEM_BIN_DIR="${RUNTIME_SRC_DIR}/functionsystem"
YR_FRONTEND_SRC_DIR="${RUNTIME_SRC_DIR}/../frontend"
YR_DASHBOARD_SRC_DIR="${RUNTIME_SRC_DIR}/go"
YR_METRICS_BIN_DIR="${RUNTIME_SRC_DIR}/metrics"
THIRD_PARTY_DIR="${RUNTIME_SRC_DIR}/thirdparty/"
RUNTIME_OUTPUT_DIR="${RUNTIME_SRC_DIR}/output"
THIRD_PARTY_LOG_DIR="${RUNTIME_OUTPUT_DIR}/logs/thirdparty"
MODULES="runtime"
bash ${BASE_DIR}/download_opensource.sh -M $MODULES -T $THIRD_PARTY_DIR
RUNTIME_THIRD_PARTY_CACHE=${RUNTIME_THIRD_PARTY_CACHE:-"https://build-logs.openeuler.openatom.cn:38080/temp-archived/openeuler/openYuanrong/runtime_deps/"}

function run_logged() {
    local name="$1"
    shift
    mkdir -p "${THIRD_PARTY_LOG_DIR}"
    local log_file="${THIRD_PARTY_LOG_DIR}/${name}.log"
    echo "[thirdparty] ${name} -> ${log_file}"
    if ! "$@" >"${log_file}" 2>&1; then
        echo "[thirdparty] ${name} failed, see ${log_file}"
        return 1
    fi
}

function download_third_party_cache() {
    if [ -n "${RUNTIME_THIRD_PARTY_CACHE}" ]; then
      wget -q -r -np -nH --no-directories ${RUNTIME_THIRD_PARTY_CACHE}
    fi
}

function download_cache() {
    if [ "$IS_MACOS" == "true" ]; then
        echo "skip runtime_deps cache on macOS"
        return
    fi
    if [ -d "${RUNTIME_SRC_DIR}/thirdparty/runtime_deps" ]; then
        echo "third party cache exist."
        return
    fi
    CACHE_OUT_DIR="${RUNTIME_SRC_DIR}/thirdparty/runtime_deps"
    mkdir -p "${CACHE_OUT_DIR}"
    pushd "${CACHE_OUT_DIR}"
    download_third_party_cache
    popd
}

function compile_all() {
    if [ ! -d "${THIRD_PARTY_DIR}/boost/lib" ]; then
        pushd "${THIRD_PARTY_DIR}/boost/"
        chmod -R 700 "${THIRD_PARTY_DIR}/boost/"
        run_logged boost-bootstrap ./bootstrap.sh --without-libraries=python
        run_logged boost-build ./b2 cxxflags=-fPIC cflags=-fPIC link=static install --with-fiber --with-atomic --prefix="${THIRD_PARTY_DIR}/boost"
        popd
    fi
    local openssl_install_dir="${THIRD_PARTY_DIR}/openssl/install_root"
    if [ ! -d "${openssl_install_dir}" ]; then
        pushd "${THIRD_PARTY_DIR}/openssl/"
        chmod -R 700 "${THIRD_PARTY_DIR}/openssl/"
        run_logged openssl-config ./config enable-ssl3 enable-ssl3-method --prefix="${openssl_install_dir}"
        run_logged openssl-build bash -lc "make -j build_libs && make install_dev"
        if [[ -d ${openssl_install_dir}/lib64 && ! -d ${openssl_install_dir}/lib ]]; then
            cp -fr ${openssl_install_dir}/lib64 ${openssl_install_dir}/lib
        fi
        popd
    fi
}

download_cache
compile_all
