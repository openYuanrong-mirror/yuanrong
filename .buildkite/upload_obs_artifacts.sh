#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

OUTPUT_FILE=""
PLATFORM=""
ARCH=""
CHANNEL="${OBS_UPLOAD_CHANNEL:-daily}"
VERSION=""
TIMESTAMP="${OBS_UPLOAD_TIMESTAMP:-$(date '+%Y%m%d%H%M%S')}"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --output)
            OUTPUT_FILE="$2"
            shift 2
            ;;
        --platform)
            PLATFORM="$2"
            shift 2
            ;;
        --arch)
            ARCH="$2"
            shift 2
            ;;
        --channel)
            CHANNEL="$2"
            shift 2
            ;;
        --version)
            VERSION="$2"
            shift 2
            ;;
        --timestamp)
            TIMESTAMP="$2"
            shift 2
            ;;
        --)
            shift
            break
            ;;
        -*)
            printf 'Unknown option: %s\n' "$1" >&2
            exit 1
            ;;
        *)
            break
            ;;
    esac
done

if [ -z "${OUTPUT_FILE}" ] || [ -z "${PLATFORM}" ] || [ -z "${ARCH}" ]; then
    printf 'Usage: %s --output FILE --platform PLATFORM --arch ARCH [--channel daily|release] [--version VERSION] FILE...\n' "$0" >&2
    exit 1
fi

if [ "${CHANNEL}" = "release" ] && [ -z "${VERSION}" ]; then
    printf '--version is required for release OBS uploads.\n' >&2
    exit 1
fi

if [ -z "${OBS_ACCESS_KEY_ID:-}" ] || [ -z "${OBS_SECRET_ACCESS_KEY:-}" ]; then
    printf 'OBS credentials are required for artifact upload.\n' >&2
    exit 1
fi

python3 -c "from obs import ObsClient"
mkdir -p "$(dirname "${OUTPUT_FILE}")"
: >"${OUTPUT_FILE}"

upload_ok=0
upload_fail=0
for file in "$@"; do
    [ -f "${file}" ] || continue
    printf 'Uploading to OBS: %s\n' "${file}" >&2
    upload_cmd=(
        python3 tools/upload_build_artifact.py
        --file "${file}"
        --kind build
        --channel "${CHANNEL}"
        --arch "${ARCH}"
        --platform "${PLATFORM}"
        --timestamp "${TIMESTAMP}"
    )
    if [ "${CHANNEL}" = "release" ]; then
        upload_cmd+=(--version "${VERSION}")
    fi
    if upload_output="$("${upload_cmd[@]}" 2>&1)"; then
        printf '%s\n' "${upload_output}"
        obs_url="$(printf '%s\n' "${upload_output}" | sed -n 's/^url: //p' | tail -n 1)"
        if [ -n "${obs_url}" ]; then
            printf '%s\t%s\n' "$(basename "${file}")" "${obs_url}" >>"${OUTPUT_FILE}"
        else
            printf 'WARNING: OBS upload succeeded without a public URL: %s\n' "${file}" >&2
        fi
        upload_ok=$((upload_ok + 1))
    else
        printf '%s\n' "${upload_output}"
        printf 'WARNING: Failed to upload %s\n' "${file}" >&2
        upload_fail=$((upload_fail + 1))
    fi
done

if [ "${upload_ok}" -eq 0 ]; then
    printf 'No files were uploaded to OBS.\n' >&2
    exit 1
fi
if [ "${upload_fail}" -ne 0 ]; then
    printf 'OBS upload failed for %s file(s).\n' "${upload_fail}" >&2
    exit 1
fi

if command -v buildkite-agent >/dev/null 2>&1 && [ -n "${BUILDKITE_STEP_KEY:-}" ]; then
    buildkite-agent meta-data set "obs-urls.${BUILDKITE_STEP_KEY}" "$(cat "${OUTPUT_FILE}")"
fi
