#!/usr/bin/env bash
set -euo pipefail

PACKAGE_REGISTRY_URL="${BUILDKITE_PACKAGE_REGISTRY_URL:-https://api.buildkite.com/v2/packages/organizations/openyuanrong/registries/openyuanrong/packages}"
PACKAGE_UPLOAD_TOKEN="${BUILDKITE_PACKAGE_UPLOAD_TOKEN:-${BUILDKITE_PACKAGES_TOKEN:-}}"
PACKAGE_UPLOAD_ENABLED="${BUILDKITE_PACKAGE_UPLOAD_ENABLED:-}"
PACKAGE_UPLOAD_REQUIRED="${BUILDKITE_PACKAGE_UPLOAD_REQUIRED:-0}"

is_enabled() {
    case "$1" in
        1|true|TRUE|yes|YES|on|ON) return 0 ;;
        *) return 1 ;;
    esac
}

if [ -z "${PACKAGE_UPLOAD_ENABLED}" ]; then
    if [ -n "${BUILDKITE_TAG:-}" ]; then
        PACKAGE_UPLOAD_ENABLED=0
    else
        PACKAGE_UPLOAD_ENABLED=1
    fi
fi

if ! is_enabled "${PACKAGE_UPLOAD_ENABLED}"; then
    printf 'BUILDKITE_PACKAGE_UPLOAD_ENABLED is disabled; skipping Buildkite package upload.\n' >&2
    exit 0
fi

if [ -z "${PACKAGE_UPLOAD_TOKEN}" ]; then
    printf 'BUILDKITE_PACKAGE_UPLOAD_TOKEN is not set; skipping Buildkite package upload.\n' >&2
    exit 0
fi

case "${PACKAGE_UPLOAD_TOKEN}" in
    bkrt_*)
        printf 'WARNING: BUILDKITE_PACKAGE_UPLOAD_TOKEN looks like a registry token; Buildkite package publishing requires an API access token with Read Packages and Write Packages scopes, or a valid OIDC token.\n' >&2
        ;;
esac

if [ "$#" -eq 0 ]; then
    printf 'No package files were requested for Buildkite package upload.\n' >&2
    exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
    printf 'Missing required CLI: curl\n' >&2
    exit 1
fi

files=()
for pattern in "$@"; do
    for file in ${pattern}; do
        [ -f "${file}" ] || continue
        files+=("${file}")
    done
done

if [ "${#files[@]}" -eq 0 ]; then
    printf 'No package files matched for Buildkite package upload.\n' >&2
    exit 0
fi

for file in "${files[@]}"; do
    printf 'Uploading %s to Buildkite Packages.\n' "${file}" >&2
    if curl --fail --show-error --silent --retry 3 --retry-all-errors \
        -X POST "${PACKAGE_REGISTRY_URL}" \
        -H "Authorization: Bearer ${PACKAGE_UPLOAD_TOKEN}" \
        -F "file=@${file}"; then
        printf '\n' >&2
    else
        status=$?
        printf 'WARNING: Buildkite package upload failed for %s.\n' "${file}" >&2
        if is_enabled "${PACKAGE_UPLOAD_REQUIRED}"; then
            exit "${status}"
        fi
        printf 'Continuing because BUILDKITE_PACKAGE_UPLOAD_REQUIRED is not enabled.\n' >&2
    fi
done
