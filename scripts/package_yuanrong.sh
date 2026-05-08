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
BUILD_VERSION=v0.0.1
BASE_DIR=$(
  cd "$(dirname "$0")"
  pwd
)
. ${BASE_DIR}/utils.sh
OUTPUT_DIR="${BASE_DIR}/../output"
RUNTIME_STAGE_DIR="${BASE_DIR}/../build/output/runtime"
FUNCTIONSYSTEM_STAGE_DIR="${BASE_DIR}/../functionsystem/output/functionsystem"
DATASYSTEM_STAGE_DIR="${BASE_DIR}/../datasystem/output/datasystem"
DATASYSTEM_FLAT_STAGE_DIR="${BASE_DIR}/../datasystem/output"
DATASYSTEM_SDK_PYTHON_STAGE_DIR="${DATASYSTEM_STAGE_DIR}/sdk/python"
DATASYSTEM_FLAT_SDK_PYTHON_STAGE_DIR="${DATASYSTEM_FLAT_STAGE_DIR}/sdk/python"
FRONTEND_STAGE_DIR="${BASE_DIR}/../frontend/output/pattern"
FAAS_STAGE_DIR="${BASE_DIR}/../go/output/pattern"
DASHBOARD_STAGE_DIR="${BASE_DIR}/../go/output"
RUNTIME_LAUNCHER_BIN="${BASE_DIR}/../functionsystem/runtime-launcher/bin/runtime/runtime-launcher"

function copy_tree_or_extract_tar() {
    local stage_dir=$1
    local tar_pattern=$2
    local dest_root=$3
    local label=$4

    local baseTime_s
    baseTime_s=$(date +%s)
    if [ -d "${stage_dir}" ]; then
        cp -a "${stage_dir}" "${dest_root}/"
        echo "[TIMER] ${label} staging copy: $(($(date +%s)-baseTime_s)) seconds"
        return
    fi

    tar -zxf ${tar_pattern} -C "${dest_root}"
    echo "[TIMER] ${label} tar extract: $(($(date +%s)-baseTime_s)) seconds"
}

function copy_dashboard_stage_or_extract_tar() {
    local stage_root=$1
    local tar_pattern=$2
    local dest_root=$3
    local label=$4

    local baseTime_s
    baseTime_s=$(date +%s)
    if [ -d "${stage_root}/bin" ] && [ -d "${stage_root}/config" ]; then
        mkdir -p "${dest_root}"
        if [ -d "${dest_root}/bin" ] || [ -d "${dest_root}/config" ]; then
            chmod -R u+w "${dest_root}/bin" "${dest_root}/config" 2>/dev/null || true
        fi
        cp -a "${stage_root}/bin/." "${dest_root}/bin/"
        cp -a "${stage_root}/config/." "${dest_root}/config/"
        echo "[TIMER] ${label} staging copy: $(($(date +%s)-baseTime_s)) seconds"
        return
    fi

    tar -zxf ${tar_pattern} -C "${dest_root}"
    echo "[TIMER] ${label} tar extract: $(($(date +%s)-baseTime_s)) seconds"
}

function copy_datasystem_sdk_python_stage_or_unzip_wheel() {
    local stage_dir=$1
    local wheel_pattern=$2
    local dest_root=$3
    local label=$4

    local baseTime_s
    baseTime_s=$(date +%s)
    mkdir -p "${dest_root}"
    if [ -d "${stage_dir}" ]; then
        cp -a "${stage_dir}/." "${dest_root}/"
        echo "[TIMER] ${label} staging copy: $(($(date +%s)-baseTime_s)) seconds"
        return
    fi

    unzip ${wheel_pattern} -d "${dest_root}"
    echo "[TIMER] ${label} wheel unzip: $(($(date +%s)-baseTime_s)) seconds"
}

function copy_datasystem_stage_or_extract_tar() {
    local stage_dir=$1
    local flat_stage_dir=$2
    local tar_pattern=$3
    local dest_root=$4
    local label=$5

    local baseTime_s
    baseTime_s=$(date +%s)
    if [ -d "${stage_dir}" ]; then
        cp -a "${stage_dir}" "${dest_root}/"
        echo "[TIMER] ${label} staging copy: $(($(date +%s)-baseTime_s)) seconds"
        return
    fi
    if [ -d "${flat_stage_dir}/sdk" ] && [ -d "${flat_stage_dir}/service" ]; then
        mkdir -p "${dest_root}/datasystem"
        cp -a "${flat_stage_dir}/sdk" "${dest_root}/datasystem/"
        cp -a "${flat_stage_dir}/service" "${dest_root}/datasystem/"
        if [ -d "${flat_stage_dir}/cpp" ]; then
            cp -a "${flat_stage_dir}/cpp" "${dest_root}/datasystem/"
        fi
        echo "[TIMER] ${label} flat staging copy: $(($(date +%s)-baseTime_s)) seconds"
        return
    fi

    tar -zxf ${tar_pattern} -C "${dest_root}"
    echo "[TIMER] ${label} tar extract: $(($(date +%s)-baseTime_s)) seconds"
}

function parse_args () {
    getopt_cmd=$(getopt -o v:h -l version:,python_bin_path:,help -- "$@")
    [ $? -ne 0 ] && exit 1
    eval set -- "$getopt_cmd"
    while true; do
        case "$1" in
        -h|--help) SHOW_HELP="true" && shift ;;
        --python_bin_path) PYTHON_BIN_PATH=$2 && shift 2 ;;
        -v|--version) BUILD_VERSION=$2 && shift 2 ;;
        --) shift && break ;;
        *) die "Invalid option: $1" && exit 1 ;;
        esac
    done

    if [ "$SHOW_HELP" != "" ]; then
        cat <<EOF
Usage:
  packaging rpm packages, args and default values:
    -v|--version             the version (=${BUILD_VERSION})
    -h|--help            show this help info
EOF
        exit 1
    fi
}

function get_all(){
  if [ -n "${FUNCTION_SYSTEM_CACHE}" ]; then
      echo "download functionsystem"
      fs_filename=$(ls *functionsystem*.tar.gz)
      if [ ! -n "${fs_filename}" ]; then
        curl -SO ${FUNCTION_SYSTEM_CACHE}
      fi
  fi
  if [ -n "${DATA_SYSTEM_CACHE}" ]; then
      echo "download datasystem"
      ds_filename=$(ls *datasystem*.tar.gz)
      if [ ! -n "${ds_filename}" ]; then
        curl -SO ${DATA_SYSTEM_CACHE}
      fi
  fi
  if [ -n "${FRONTEND_CACHE}" ]; then
      echo "download frontend"
      frontend_filename=$(ls *frontend*.tar.gz)
      if [ ! -n "${frontend_filename}" ]; then
        curl -SO ${FRONTEND_CACHE}
      fi
  fi
  if [ -n "${DASHBOARD_CACHE}" ]; then
      echo "download dashboard"
      dashboard_filename=$(ls *dashboard*.tar.gz)
      if [ ! -n "${dashboard_filename}" ]; then
        curl -SO ${DASHBOARD_CACHE}
      fi
  fi
}

function main () {
    parse_args "$@"
}



main $@
rm -rf ${OUTPUT_DIR}/openyuanrong
mkdir -p ${OUTPUT_DIR}/openyuanrong
cd ${OUTPUT_DIR}

get_all

baseTime_s=$(date +%s)
copy_tree_or_extract_tar "${RUNTIME_STAGE_DIR}" "yr-runtime-*.tar.gz" "${OUTPUT_DIR}/openyuanrong" "runtime"
copy_tree_or_extract_tar "${FUNCTIONSYSTEM_STAGE_DIR}" "*functionsystem*.tar.gz" "${OUTPUT_DIR}/openyuanrong" "functionsystem"
copy_datasystem_stage_or_extract_tar \
    "${DATASYSTEM_STAGE_DIR}" \
    "${DATASYSTEM_FLAT_STAGE_DIR}" \
    "*datasystem*.tar.gz" \
    "${OUTPUT_DIR}/openyuanrong" \
    "datasystem"
echo "[TIMER] Populate openyuanrong base tree: $(($(date +%s)-baseTime_s)) seconds"

if [ -f "${RUNTIME_LAUNCHER_BIN}" ]; then
  mkdir -p ${OUTPUT_DIR}/openyuanrong/functionsystem/bin
  cp "${RUNTIME_LAUNCHER_BIN}" ${OUTPUT_DIR}/openyuanrong/functionsystem/bin/
fi

rm -rf ${OUTPUT_DIR}/openyuanrong/datasystem/sdk/DATASYSTEM_SYM
rm -rf ${OUTPUT_DIR}/openyuanrong/datasystem/service/DATASYSTEM_SYM
mkdir -p ${OUTPUT_DIR}/openyuanrong/datasystem/deploy
cp -fr ${BASE_DIR}/../deploy/data_system/* ${OUTPUT_DIR}/openyuanrong/datasystem/deploy/
baseTime_s=$(date +%s)
datasystem_python_stage_dir="${DATASYSTEM_SDK_PYTHON_STAGE_DIR}"
if [ ! -d "${datasystem_python_stage_dir}" ]; then
    datasystem_python_stage_dir="${DATASYSTEM_FLAT_SDK_PYTHON_STAGE_DIR}"
fi
copy_datasystem_sdk_python_stage_or_unzip_wheel \
    "${datasystem_python_stage_dir}" \
    "${OUTPUT_DIR}/openyuanrong/datasystem/sdk/openyuanrong_datasystem_sdk*.whl" \
    "${OUTPUT_DIR}/openyuanrong/runtime/service/python/" \
    "Expand datasystem sdk python payload into runtime python service"
echo "[TIMER] Populate runtime python service datasystem sdk payload: $(($(date +%s)-baseTime_s)) seconds"

cp -fr ${BASE_DIR}/../deploy ${OUTPUT_DIR}/openyuanrong
rm -rf ${OUTPUT_DIR}/openyuanrong/deploy/data_system

if [ -d "${BASE_DIR}/../../yuanrong-datasystem" ];then
  mkdir -p ${OUTPUT_DIR}/openyuanrong/deploy/k8s/build/datasystem
  cp -fr ${BASE_DIR}/../../yuanrong-datasystem/k8s/helm_chart/datasystem ${OUTPUT_DIR}/openyuanrong/deploy/k8s/charts/
  cp -fr ${BASE_DIR}/../../yuanrong-datasystem/k8s/docker/* ${OUTPUT_DIR}/openyuanrong/deploy/k8s/build/datasystem/
fi

frontend_filename=$(ls *frontend*.tar.gz)
if [ -n "${frontend_filename}" ]; then
    copy_tree_or_extract_tar "${FRONTEND_STAGE_DIR}" "${frontend_filename}" "${OUTPUT_DIR}/openyuanrong" "frontend"
    cp -fr ${OUTPUT_DIR}/openyuanrong/pattern/pattern_faas/init_frontend_args.json ${OUTPUT_DIR}/openyuanrong/functionsystem/config/
fi

faas_filename=$(ls *faas*.tar.gz)
if [ -n "${faas_filename}" ]; then
    copy_tree_or_extract_tar "${FAAS_STAGE_DIR}" "${faas_filename}" "${OUTPUT_DIR}/openyuanrong" "faas"
    cp -fr ${OUTPUT_DIR}/openyuanrong/pattern/pattern_faas/init_scheduler_args.json ${OUTPUT_DIR}/openyuanrong/functionsystem/config/
fi

dashboard_filename=$(ls *dashboard*.tar.gz)
if [ -n "${dashboard_filename}" ]; then
    copy_dashboard_stage_or_extract_tar "${DASHBOARD_STAGE_DIR}" "${dashboard_filename}" "${OUTPUT_DIR}/openyuanrong/functionsystem/" "dashboard"
fi

find . -type d -exec chmod 750 {} \;
find . -type l -exec chmod 777 {} \;
find . -type f -exec chmod 640 {} \;
find . -type d -name bin -exec chmod -R 755 {} \;
find . -type f -name datasystem_worker -exec chmod 755 {} \;
find . -type f -name "etcd*" -exec chmod 550 {} \;
if [ -d ${OUTPUT_DIR}/openyuanrong/deploy/process/ ]; then
  find ${OUTPUT_DIR}/openyuanrong/deploy/process/ -type f -exec chmod 550 {} \;
  find ${OUTPUT_DIR}/openyuanrong/deploy/process/ -type f -name "*.yaml" -exec chmod 640 {} \;
fi

if [ -d ${OUTPUT_DIR}/openyuanrong/datasystem/ ]; then
  find ${OUTPUT_DIR}/openyuanrong/datasystem/ -type f -exec chmod 550 {} \;
fi

mv ${OUTPUT_DIR}/openyuanrong/functionsystem/deploy/third_party ${OUTPUT_DIR}/openyuanrong/
mv ${OUTPUT_DIR}/openyuanrong/functionsystem/deploy/function_system/* ${OUTPUT_DIR}/openyuanrong/functionsystem/deploy/
rm -rf ${OUTPUT_DIR}/openyuanrong/functionsystem/deploy/function_system/
mv ${OUTPUT_DIR}/openyuanrong/functionsystem/deploy/vendor/etcd ${OUTPUT_DIR}/openyuanrong/third_party/
rm -rf ${OUTPUT_DIR}/openyuanrong/functionsystem/deploy/vendor
if [ -d ${OUTPUT_DIR}/openyuanrong/third_party/ ]; then
  find ${OUTPUT_DIR}/openyuanrong/third_party/ -type f -exec chmod 550 {} \;
fi

if [ -d ${OUTPUT_DIR}/openyuanrong/functionsystem/ ]; then
  find ${OUTPUT_DIR}/openyuanrong/functionsystem/ -type f -exec chmod 550 {} \;
fi
if [ -d ${OUTPUT_DIR}/openyuanrong/functionsystem/config/ ]; then
  find ${OUTPUT_DIR}/openyuanrong/functionsystem/config/ -type f -exec chmod 640 {} \;
fi

if [ -d ${OUTPUT_DIR}/openyuanrong/runtime/deploy/process/ ]; then
  find ${OUTPUT_DIR}/openyuanrong/runtime/deploy/process/ -type f -exec chmod 550 {} \;
fi
if [ -d ${OUTPUT_DIR}/openyuanrong/runtime/sdk/ ]; then
  find ${OUTPUT_DIR}/openyuanrong/runtime/sdk/ -type f -exec chmod 550 {} \;
  find ${OUTPUT_DIR}/openyuanrong/runtime/sdk/ -type f -name "*.xml" -exec chmod 640 {} \;
fi
if [ -d ${OUTPUT_DIR}/openyuanrong/runtime/service/java/ ]; then
  find ${OUTPUT_DIR}/openyuanrong/runtime/service/java/ -type f -exec chmod 550 {} \;
  find ${OUTPUT_DIR}/openyuanrong/runtime/service/java/ -type f -name "*.xml" -exec chmod 640 {} \;
fi
if [ -d ${OUTPUT_DIR}/openyuanrong/runtime/service/cpp/ ]; then
  find ${OUTPUT_DIR}/openyuanrong/runtime/service/cpp/ -type f -exec chmod 550 {} \;
fi
if [ -d ${OUTPUT_DIR}/openyuanrong/runtime/service/cpp/config/ ]; then
  find ${OUTPUT_DIR}/openyuanrong/runtime/service/cpp/config/ -type f -exec chmod 640 {} \;
fi
if [ -d ${OUTPUT_DIR}/openyuanrong/runtime/service/python/ ]; then
  find ${OUTPUT_DIR}/openyuanrong/runtime/service/python/ -type f -exec chmod 550 {} \;
fi
if [ -d ${OUTPUT_DIR}/openyuanrong/runtime/service/python/config/ ]; then
  find ${OUTPUT_DIR}/openyuanrong/runtime/service/python/config/ -type f -exec chmod 640 {} \;
fi
if [ -d ${OUTPUT_DIR}/openyuanrong/runtime/service/python/yr/config/ ]; then
  find ${OUTPUT_DIR}/openyuanrong/runtime/service/python/yr/config/ -type f -exec chmod 640 {} \;
fi

cat >${OUTPUT_DIR}/openyuanrong/VERSION <<EOF
"${BUILD_VERSION}"
EOF
[ -d "${OUTPUT_DIR}/openyuanrong/runtime/sdk/cpp" ] && cp -ar ${OUTPUT_DIR}/openyuanrong/VERSION ${OUTPUT_DIR}/openyuanrong/runtime/sdk/cpp/VERSION

baseTime_s=$(date +%s)
tar -zcf openyuanrong-${BUILD_VERSION}.tar.gz openyuanrong
echo "[TIMER] Archive combined openyuanrong package: $(($(date +%s)-baseTime_s)) seconds"
