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
DATASYSTEM_SOURCE_DIR="${BASE_DIR}/../datasystem"
LEGACY_DATASYSTEM_SOURCE_DIR="${BASE_DIR}/../../yuanrong-datasystem"

function resolve_first_match() {
    local pattern=$1
    local matches=()
    shopt -s nullglob
    matches=(${pattern})
    shopt -u nullglob
    if [ ${#matches[@]} -eq 0 ]; then
        return 1
    fi
    printf '%s\n' "${matches[0]}"
}

function download_archive() {
    local url=$1
    local output_name
    local tmp_name
    local attempt

    output_name=$(basename "${url%%\?*}")
    tmp_name="${output_name}.tmp"
    for attempt in 1 2 3; do
        rm -f "${tmp_name}"
        curl -fL --retry 3 --retry-delay 2 --retry-all-errors -o "${tmp_name}" "${url}"
        if [[ "${output_name}" == *.tar.gz ]]; then
            if ! gzip -t "${tmp_name}"; then
                echo "Downloaded archive ${output_name} failed gzip validation, retry ${attempt}/3"
                continue
            fi
        fi
        mv "${tmp_name}" "${output_name}"
        return
    done
    rm -f "${tmp_name}"
    die "Failed to download a valid archive from ${url}"
}

function copy_tree_or_extract_tar() {
    local stage_dir=$1
    local tar_pattern=$2
    local dest_root=$3
    local label=$4
    local tar_file

    local baseTime_s
    baseTime_s=$(date +%s)
    if [ -d "${stage_dir}" ]; then
        cp -a "${stage_dir}" "${dest_root}/"
        echo "[TIMER] ${label} staging copy: $(($(date +%s)-baseTime_s)) seconds"
        return
    fi

    tar_file=$(resolve_first_match "${tar_pattern}") || die "No archive matched pattern: ${tar_pattern}"
    tar -zxf "${tar_file}" -C "${dest_root}"
    echo "[TIMER] ${label} tar extract: $(($(date +%s)-baseTime_s)) seconds"
}

function copy_dashboard_stage_or_extract_tar() {
    local stage_root=$1
    local tar_pattern=$2
    local dest_root=$3
    local label=$4
    local tar_file

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

    tar_file=$(resolve_first_match "${tar_pattern}") || die "No archive matched pattern: ${tar_pattern}"
    tar -zxf "${tar_file}" -C "${dest_root}"
    echo "[TIMER] ${label} tar extract: $(($(date +%s)-baseTime_s)) seconds"
}

function copy_datasystem_sdk_python_stage_or_unzip_wheel() {
    local stage_dir=$1
    local wheel_pattern=$2
    local dest_root=$3
    local label=$4
    local wheel_file

    local baseTime_s
    baseTime_s=$(date +%s)
    mkdir -p "${dest_root}"
    if [ -d "${stage_dir}" ]; then
        cp -a "${stage_dir}/." "${dest_root}/"
        echo "[TIMER] ${label} staging copy: $(($(date +%s)-baseTime_s)) seconds"
        return
    fi

    wheel_file=$(resolve_first_match "${wheel_pattern}") || die "No wheel matched pattern: ${wheel_pattern}"
    unzip "${wheel_file}" -d "${dest_root}"
    echo "[TIMER] ${label} wheel unzip: $(($(date +%s)-baseTime_s)) seconds"
}

function copy_datasystem_stage_or_extract_tar() {
    local stage_dir=$1
    local flat_stage_dir=$2
    local tar_pattern=$3
    local dest_root=$4
    local label=$5
    local tar_file

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

    tar_file=$(resolve_first_match "${tar_pattern}") || die "No archive matched pattern: ${tar_pattern}"
    tar -zxf "${tar_file}" -C "${dest_root}"
    echo "[TIMER] ${label} tar extract: $(($(date +%s)-baseTime_s)) seconds"
}

function copy_datasystem_k8s_assets() {
    local source_dir=""
    local chart_dir
    local docker_dir
    local chart_dest="${OUTPUT_DIR}/openyuanrong/deploy/k8s/charts"
    local docker_dest="${OUTPUT_DIR}/openyuanrong/deploy/k8s/build/datasystem"

    if [ -d "${DATASYSTEM_SOURCE_DIR}/k8s/helm_chart/datasystem" ]; then
        source_dir="${DATASYSTEM_SOURCE_DIR}"
    elif [ -d "${LEGACY_DATASYSTEM_SOURCE_DIR}/k8s/helm_chart/datasystem" ]; then
        source_dir="${LEGACY_DATASYSTEM_SOURCE_DIR}"
    else
        echo "Skip datasystem k8s assets: no datasystem helm chart found"
        return
    fi

    chart_dir="${source_dir}/k8s/helm_chart/datasystem"
    docker_dir="${source_dir}/k8s/docker"
    mkdir -p "${chart_dest}"
    cp -fr "${chart_dir}" "${chart_dest}/"
    echo "Copied datasystem helm chart from ${chart_dir}"

    if [ -d "${docker_dir}" ]; then
        mkdir -p "${docker_dest}"
        cp -fr "${docker_dir}/." "${docker_dest}/"
        echo "Copied datasystem k8s docker files from ${docker_dir}"
    else
        echo "Skip datasystem k8s docker files: ${docker_dir} not found"
    fi
}

function ensure_openssl_linker_symlinks() {
    local lib_dir=$1
    local source_dir=${2:-$1}

    ensure_openssl_linker_symlinks_from_sources "${lib_dir}" "${source_dir}"
}

function relative_path_between_dirs() {
    local from_dir=$1
    local to_dir=$2
    local from_abs
    local to_abs
    local from_parts
    local to_parts
    local i=0
    local j
    local rel_path=""

    from_abs=$(cd "${from_dir}" && pwd -P) || return
    to_abs=$(cd "${to_dir}" && pwd -P) || return
    IFS='/' read -r -a from_parts <<< "${from_abs#/}"
    IFS='/' read -r -a to_parts <<< "${to_abs#/}"

    while [ ${i} -lt ${#from_parts[@]} ] && [ ${i} -lt ${#to_parts[@]} ] && \
        [ "${from_parts[$i]}" = "${to_parts[$i]}" ]; do
        i=$((i + 1))
    done

    for ((j = i; j < ${#from_parts[@]}; j++)); do
        rel_path="${rel_path}../"
    done
    for ((j = i; j < ${#to_parts[@]}; j++)); do
        rel_path="${rel_path}${to_parts[$j]}/"
    done
    rel_path="${rel_path%/}"
    [ -n "${rel_path}" ] || rel_path="."
    printf '%s\n' "${rel_path}"
}

function ensure_openssl_linker_symlinks_from_sources() {
    local lib_dir=$1
    shift
    local source_dirs=("$@")
    local lib_name
    local link_path
    local target_path
    local target_name
    local source_dir
    local source_prefix
    local created

    if [ ! -d "${lib_dir}" ]; then
        echo "Warning: skip OpenSSL linker symlink creation, lib dir not found: ${lib_dir}" >&2
        return
    fi
    if [ ${#source_dirs[@]} -eq 0 ]; then
        echo "Warning: skip OpenSSL linker symlink creation, no source dirs provided for ${lib_dir}" >&2
        return
    fi

    for lib_name in ssl crypto; do
        link_path="${lib_dir}/lib${lib_name}.so"
        if [ -e "${link_path}" ] || [ -L "${link_path}" ]; then
            continue
        fi

        created=false
        for source_dir in "${source_dirs[@]}"; do
            [ -d "${source_dir}" ] || continue
            target_path="${source_dir}/lib${lib_name}.so.1.1"
            if [ ! -e "${target_path}" ]; then
                target_path=$(resolve_first_match "${source_dir}/lib${lib_name}.so.*") || continue
            fi
            target_name="$(basename "${target_path}")"
            if [ "${source_dir}" != "${lib_dir}" ]; then
                source_prefix=$(relative_path_between_dirs "${lib_dir}" "${source_dir}") || continue
                target_name="${source_prefix}/${target_name}"
            fi
            ln -s "${target_name}" "${link_path}"
            created=true
            break
        done
        if [ "${created}" != true ]; then
            echo "Warning: skip ${link_path}, no lib${lib_name}.so.* found in candidate dirs: ${source_dirs[*]}" >&2
        fi
    done
}

function ensure_package_openssl_linker_symlinks() {
    local package_root=$1
    local openssl_source_dirs=(
        "${package_root}/runtime/sdk/cpp/lib"
        "${package_root}/functionsystem/lib"
        "${package_root}/datasystem/sdk/cpp/lib"
        "${package_root}/datasystem/sdk/go/lib"
        "${package_root}/datasystem/service/lib"
        "${package_root}/runtime/service/python/yr/datasystem/lib"
    )
    local openssl_target_dirs=(
        "${package_root}/runtime/sdk/cpp/lib"
        "${package_root}/datasystem/sdk/cpp/lib"
        "${package_root}/datasystem/sdk/go/lib"
        "${package_root}/runtime/service/python/yr/datasystem/lib"
    )
    local target_dir

    for target_dir in "${openssl_target_dirs[@]}"; do
        [ -d "${target_dir}" ] || continue
        ensure_openssl_linker_symlinks_from_sources "${target_dir}" "${openssl_source_dirs[@]}"
    done
}

function require_release_file() {
    local pattern=$1
    local label=$2
    local matched

    matched=$(resolve_first_match "${pattern}") || die "Missing ${label}: ${pattern}"
    echo "Verified ${label}: ${matched}"
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
        download_archive "${FUNCTION_SYSTEM_CACHE}"
      fi
  fi
  if [ -n "${DATA_SYSTEM_CACHE}" ]; then
      echo "download datasystem"
      ds_filename=$(ls *datasystem*.tar.gz)
      if [ ! -n "${ds_filename}" ]; then
        download_archive "${DATA_SYSTEM_CACHE}"
      fi
  fi
  if [ -n "${FRONTEND_CACHE}" ]; then
      echo "download frontend"
      frontend_filename=$(ls *frontend*.tar.gz)
      if [ ! -n "${frontend_filename}" ]; then
        download_archive "${FRONTEND_CACHE}"
      fi
  fi
  if [ -n "${DASHBOARD_CACHE}" ]; then
      echo "download dashboard"
      dashboard_filename=$(ls *dashboard*.tar.gz)
      if [ ! -n "${dashboard_filename}" ]; then
        download_archive "${DASHBOARD_CACHE}"
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
ensure_package_openssl_linker_symlinks "${OUTPUT_DIR}/openyuanrong"
echo "[TIMER] Populate runtime python service datasystem sdk payload: $(($(date +%s)-baseTime_s)) seconds"

mkdir -p "${OUTPUT_DIR}/openyuanrong/runtime/service/python"
cp -f "${BASE_DIR}/../api/python/requirements.txt" \
    "${OUTPUT_DIR}/openyuanrong/runtime/service/python/requirements.txt"

cp -fr ${BASE_DIR}/../deploy ${OUTPUT_DIR}/openyuanrong
rm -rf ${OUTPUT_DIR}/openyuanrong/deploy/data_system

copy_datasystem_k8s_assets

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
    copy_dashboard_stage_or_extract_tar "${DASHBOARD_STAGE_DIR}" "${dashboard_filename}" "${OUTPUT_DIR}/openyuanrong/dashboard/" "dashboard"
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

require_release_file \
  "${OUTPUT_DIR}/openyuanrong/datasystem/sdk/datasystem-*_*.jar" \
  "datasystem Java SDK jar"
require_release_file \
  "${OUTPUT_DIR}/openyuanrong/datasystem/sdk/openyuanrong_datasystem_sdk*.whl" \
  "datasystem Python SDK wheel"
require_release_file \
  "${OUTPUT_DIR}/openyuanrong/runtime/sdk/java/faas-function-sdk-*.jar" \
  "FaaS Java SDK jar"
require_release_file \
  "${OUTPUT_DIR}/openyuanrong/runtime/sdk/java/yr-api-sdk-*.jar" \
  "YuanRong Java API SDK jar"

baseTime_s=$(date +%s)
tar -zcf openyuanrong-${BUILD_VERSION}.tar.gz openyuanrong
echo "[TIMER] Archive combined openyuanrong package: $(($(date +%s)-baseTime_s)) seconds"
