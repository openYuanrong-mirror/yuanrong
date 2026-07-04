#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

SANDBOX_ARTIFACT_DIR="${ROOT_DIR}/artifacts/sandbox"
HELM_DIR="${SANDBOX_ARTIFACT_DIR}/helm"
MANIFEST_DIR="${SANDBOX_ARTIFACT_DIR}/manifests"
METADATA_DIR="${SANDBOX_ARTIFACT_DIR}/metadata"
ARCHIVE_DIR="${SANDBOX_ARTIFACT_DIR}/archive"
CHART_DIR="${ROOT_DIR}/deploy/sandbox/k8s/charts/yr-k8s"
VALUES_FILE="${ROOT_DIR}/deploy/sandbox/k8s/k8s/values.prod.yaml"
REGISTRY_REPO="${YR_K8S_REGISTRY_REPO:-swr.cn-southwest-2.myhuaweicloud.com/openyuanrong}"
REGISTRY_SERVER="${YR_K8S_REGISTRY_SERVER:-${REGISTRY_REPO%%/*}}"
TRAEFIK_IMAGE_REGISTRY="${YR_K8S_TRAEFIK_IMAGE_REGISTRY:-${REGISTRY_REPO}}"
TRAEFIK_IMAGE_TAG="${YR_K8S_TRAEFIK_IMAGE_TAG:-v2.11.14}"
COMMIT_SHA="${BUILDKITE_COMMIT:-$(git rev-parse HEAD)}"
SHORT_SHA="${COMMIT_SHA:0:12}"
BUILD_NUMBER="${BUILDKITE_BUILD_NUMBER:-0}"
BRANCH_NAME="${BUILDKITE_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
SANITIZED_BRANCH="$(printf '%s' "${BRANCH_NAME}" | tr '/:_@' '----' | tr -cd '[:alnum:].-' | cut -c1-64)"
[ -n "${SANITIZED_BRANCH}" ] || SANITIZED_BRANCH="build"
IMAGE_TAG="${YR_K8S_IMAGE_TAG:-${SANITIZED_BRANCH}-${BUILD_NUMBER}-${SHORT_SHA}}"
IMAGE_ARCHES="${YR_K8S_MANIFEST_ARCHES:-amd64 arm64}"
DEFAULT_RUNTIME_SDK_SUFFIX="${YR_K8S_DEFAULT_RUNTIME_SDK_SUFFIX:-cp310}"
RUNTIME_IMAGE_TAG="${YR_K8S_RUNTIME_IMAGE_TAG:-${IMAGE_TAG}-${DEFAULT_RUNTIME_SDK_SUFFIX}}"
CHART_VERSION="${YR_K8S_CHART_VERSION:-0.1.0+buildkite.${BUILD_NUMBER}.${SHORT_SHA}}"
APP_VERSION="${YR_K8S_APP_VERSION:-${SHORT_SHA}}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
LINUX_AMD64_SDK_STEPS="${SANDBOX_AMD64_SDK_STEPS:-build-sdk-amd64-cp39 build-sdk-amd64-cp310 build-sdk-amd64-cp311 build-sdk-amd64-cp312 build-sdk-amd64-cp313}"
LINUX_ARM64_SDK_STEPS="${SANDBOX_ARM64_SDK_STEPS:-build-sdk-arm64-cp39 build-sdk-arm64-cp310 build-sdk-arm64-cp311 build-sdk-arm64-cp312 build-sdk-arm64-cp313}"
MACOS_ARM64_SDK_STEPS="${SANDBOX_MACOS_ARM64_SDK_STEPS:-build-sdk-macos-arm64-cp39 build-sdk-macos-arm64-cp310 build-sdk-macos-arm64-cp311 build-sdk-macos-arm64-cp312 build-sdk-macos-arm64-cp313}"
RRT_ARTIFACT_STEPS="${SANDBOX_RRT_ARTIFACT_STEPS:-build-rrt-amd64 build-rrt-arm64}"
SANDBOX_SDK_ARTIFACT_STEPS="${SANDBOX_SANDBOX_SDK_STEPS:-test-sandbox-sdk}"
EXTRA_ARTIFACT_STEPS="${SANDBOX_EXTRA_ARTIFACT_STEPS:-}"
RUNTIME_IMAGE_STEPS="${SANDBOX_RUNTIME_IMAGE_STEPS:-}"

local_images=(yr-base yr-compile yr-runtime yr-controlplane yr-node)

require_bin() {
    local bin_name="$1"
    if ! command -v "${bin_name}" >/dev/null 2>&1; then
        printf 'Missing required CLI: %s\n' "${bin_name}" >&2
        exit 1
    fi
}

docker_login_if_configured() {
    if [ -z "${SWR_USERNAME:-}" ] || [ -z "${SWR_PASSWORD:-}" ]; then
        if [ -n "${SWR_DOCKER_CONFIG_JSON:-}" ]; then
            mkdir -p "${HOME}/.docker"
            printf '%s' "${SWR_DOCKER_CONFIG_JSON}" >"${HOME}/.docker/config.json"
            printf 'Using Docker registry config from swr-pull-secret.\n' >&2
            return 0
        fi
        if [[ "${REGISTRY_SERVER}" == swr.*.myhuaweicloud.com ]]; then
            printf 'SWR_USERNAME/SWR_PASSWORD are required to push manifests to %s.\n' "${REGISTRY_SERVER}" >&2
            exit 1
        fi
        printf 'SWR_USERNAME/SWR_PASSWORD not set; assuming docker is already authenticated.\n' >&2
        return 0
    fi

    printf '%s' "${SWR_PASSWORD}" | "${DOCKER_BIN}" login "${REGISTRY_SERVER}" -u "${SWR_USERNAME}" --password-stdin
}

manifest_source_args() {
    local image_name="$1"
    local source_tag_suffix="${2:-}"
    local arch
    for arch in ${IMAGE_ARCHES}; do
        printf '%s/%s:%s-%s%s\n' "${REGISTRY_REPO}" "${image_name}" "${IMAGE_TAG}" "${arch}" "${source_tag_suffix}"
    done
}

create_manifest() {
    local image_name="$1"
    local target_tag="${2:-${IMAGE_TAG}}"
    local source_tag_suffix="${3:-}"
    local target="${REGISTRY_REPO}/${image_name}:${target_tag}"
    local arch
    local source
    local sources=()

    mapfile -t sources < <(manifest_source_args "${image_name}" "${source_tag_suffix}")
    printf 'Creating manifest %s from:\n' "${target}" >&2
    printf '  %s\n' "${sources[@]}" >&2

    "${DOCKER_BIN}" manifest rm "${target}" >/dev/null 2>&1 || true
    "${DOCKER_BIN}" manifest create "${target}" "${sources[@]}"
    for arch in ${IMAGE_ARCHES}; do
        source="${REGISTRY_REPO}/${image_name}:${IMAGE_TAG}-${arch}${source_tag_suffix}"
        "${DOCKER_BIN}" manifest annotate "${target}" "${source}" --os linux --arch "${arch}"
    done
    "${DOCKER_BIN}" manifest push --purge "${target}"
}

runtime_sdk_suffixes() {
    local step_key
    local sdk_suffix
    local seen=" "

    for step_key in ${RUNTIME_IMAGE_STEPS}; do
        case "${step_key}" in
            publish-runtime-*-*)
                sdk_suffix="${step_key##*-}"
                ;;
            *)
                continue
                ;;
        esac
        case "${seen}" in
            *" ${sdk_suffix} "*) continue ;;
        esac
        seen="${seen}${sdk_suffix} "
        printf '%s\n' "${sdk_suffix}"
    done
}

write_values_override() {
    cat >"${METADATA_DIR}/yr-k8s-image-values.yaml" <<EOF
global:
  imageRegistry: ${REGISTRY_REPO}
  images:
    controlplane:
      repository: yr-controlplane
      tag: ${IMAGE_TAG}
    node:
      repository: yr-node
      tag: ${IMAGE_TAG}
    runtime:
      repository: yr-runtime
      tag: ${RUNTIME_IMAGE_TAG}
    traefik:
      registry: ${TRAEFIK_IMAGE_REGISTRY}
      repository: traefik
      tag: ${TRAEFIK_IMAGE_TAG}
EOF
}

write_metadata() {
    cat >"${METADATA_DIR}/sandbox-release.json" <<EOF
{
  "commit": "${COMMIT_SHA}",
  "branch": "${BRANCH_NAME}",
  "build_number": "${BUILD_NUMBER}",
  "registry": "${REGISTRY_REPO}",
  "image_tag": "${IMAGE_TAG}",
  "runtime_image_tag": "${RUNTIME_IMAGE_TAG}",
  "image_arches": "$(printf '%s' "${IMAGE_ARCHES}")",
  "chart_version": "${CHART_VERSION}",
  "app_version": "${APP_VERSION}",
  "images": [
    "${REGISTRY_REPO}/yr-controlplane:${IMAGE_TAG}",
    "${REGISTRY_REPO}/yr-node:${IMAGE_TAG}",
    "${REGISTRY_REPO}/yr-runtime:${RUNTIME_IMAGE_TAG}"
  ],
  "static_images": [
    "${TRAEFIK_IMAGE_REGISTRY}/traefik:${TRAEFIK_IMAGE_TAG}"
  ]
}
EOF
}

collect_artifact_archive() {
    rm -rf "${ARCHIVE_DIR}"
    mkdir -p \
        "${ARCHIVE_DIR}/linux-amd64" \
        "${ARCHIVE_DIR}/linux-amd64-sdk" \
        "${ARCHIVE_DIR}/linux-arm64" \
        "${ARCHIVE_DIR}/linux-arm64-sdk" \
        "${ARCHIVE_DIR}/macos-arm64-sdk" \
        "${ARCHIVE_DIR}/sandbox-sdk" \
        "${ARCHIVE_DIR}/rrt" \
        "${ARCHIVE_DIR}/extra" \
        "${ARCHIVE_DIR}/runtime-images"

    if ! command -v buildkite-agent >/dev/null 2>&1; then
        return 0
    fi

    buildkite-agent meta-data get "obs-urls.build-all-amd64" \
        >"${ARCHIVE_DIR}/linux-amd64/obs-urls.txt" || true
    for step_key in ${LINUX_AMD64_SDK_STEPS}; do
        mkdir -p "${ARCHIVE_DIR}/linux-amd64-sdk/${step_key}"
        buildkite-agent meta-data get "obs-urls.${step_key}" \
            >"${ARCHIVE_DIR}/linux-amd64-sdk/${step_key}/obs-urls.txt" || true
    done
    buildkite-agent meta-data get "obs-urls.build-all-arm64" \
        >"${ARCHIVE_DIR}/linux-arm64/obs-urls.txt" || true
    for step_key in ${LINUX_ARM64_SDK_STEPS}; do
        mkdir -p "${ARCHIVE_DIR}/linux-arm64-sdk/${step_key}"
        buildkite-agent meta-data get "obs-urls.${step_key}" \
            >"${ARCHIVE_DIR}/linux-arm64-sdk/${step_key}/obs-urls.txt" || true
    done
    for step_key in ${MACOS_ARM64_SDK_STEPS}; do
        mkdir -p "${ARCHIVE_DIR}/macos-arm64-sdk/${step_key}"
        buildkite-agent meta-data get "obs-urls.${step_key}" \
            >"${ARCHIVE_DIR}/macos-arm64-sdk/${step_key}/obs-urls.txt" || true
    done
    for step_key in ${SANDBOX_SDK_ARTIFACT_STEPS}; do
        mkdir -p "${ARCHIVE_DIR}/sandbox-sdk/${step_key}"
        buildkite-agent meta-data get "obs-urls.${step_key}" \
            >"${ARCHIVE_DIR}/sandbox-sdk/${step_key}/obs-urls.txt" || true
    done
    for step_key in ${RRT_ARTIFACT_STEPS}; do
        mkdir -p "${ARCHIVE_DIR}/rrt/${step_key}"
        buildkite-agent meta-data get "obs-urls.${step_key}" \
            >"${ARCHIVE_DIR}/rrt/${step_key}/obs-urls.txt" || true
    done
    for step_key in ${EXTRA_ARTIFACT_STEPS}; do
        mkdir -p "${ARCHIVE_DIR}/extra/${step_key}"
        buildkite-agent meta-data get "obs-urls.${step_key}" \
            >"${ARCHIVE_DIR}/extra/${step_key}/obs-urls.txt" || true
    done
    for step_key in ${RUNTIME_IMAGE_STEPS}; do
        case "${step_key}" in
            publish-runtime-amd64-*)
                printf '%s\n' "${REGISTRY_REPO}/yr-runtime:${IMAGE_TAG}-amd64-${step_key##*-}" \
                    >"${ARCHIVE_DIR}/runtime-images/${IMAGE_TAG}-amd64-${step_key##*-}.txt"
                ;;
            publish-runtime-arm64-*)
                printf '%s\n' "${REGISTRY_REPO}/yr-runtime:${IMAGE_TAG}-arm64-${step_key##*-}" \
                    >"${ARCHIVE_DIR}/runtime-images/${IMAGE_TAG}-arm64-${step_key##*-}.txt"
                ;;
        esac
    done
}

write_artifact_summary_json() {
    python3 - "${ARCHIVE_DIR}" "${METADATA_DIR}/build-artifacts.json" "${BUILD_NUMBER}" "${BRANCH_NAME}" "${COMMIT_SHA}" "${REGISTRY_REPO}" "${IMAGE_TAG}" <<'PY'
import json
import pathlib
import sys

archive_dir = pathlib.Path(sys.argv[1]).resolve()
output_path = pathlib.Path(sys.argv[2])
build_number, branch_name, commit_sha, registry, image_tag = sys.argv[3:8]

artifact_groups = {}
for obs_file in sorted(archive_dir.rglob("obs-urls.txt")):
    rel = obs_file.relative_to(archive_dir)
    group = rel.parts[0] if rel.parts else "unknown"
    step = rel.parts[1] if len(rel.parts) > 2 else group
    for line in obs_file.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        fields = line.split("\t", 1)
        if len(fields) != 2:
            continue
        name, url = fields
        artifact_groups.setdefault(group, []).append({
            "step": step,
            "name": name,
            "url": url,
        })

runtime_images = []
for tag_file in sorted((archive_dir / "runtime-images").glob("*.txt")):
    for line in tag_file.read_text(errors="replace").splitlines():
        line = line.strip()
        if line:
            runtime_images.append(line)

summary = {
    "build_number": build_number,
    "branch": branch_name,
    "commit": commit_sha,
    "registry": registry,
    "image_tag": image_tag,
    "artifact_groups": artifact_groups,
    "runtime_images": sorted(set(runtime_images)),
}
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

upload_manifest_artifacts_to_obs_if_configured() {
    if [ -z "${OBS_ACCESS_KEY_ID:-}" ] || [ -z "${OBS_SECRET_ACCESS_KEY:-}" ]; then
        if command -v buildkite-agent >/dev/null 2>&1; then
            printf 'OBS credentials are required for manifest artifact upload.\n' >&2
            exit 1
        fi
        printf 'OBS credentials not set; skipping manifest artifact upload to OBS.\n' >&2
        return 0
    fi

    local release_tag="${YR_RELEASE_TAG:-${BUILDKITE_TAG:-}}"
    release_tag="${release_tag#refs/tags/}"
    case "${release_tag}" in
        v[0-9]*) release_tag="${release_tag#v}" ;;
    esac
    local obs_channel="daily"
    local version_args=()
    if [ -n "${release_tag}" ]; then
        obs_channel="release"
        version_args=(--version "${release_tag}")
    fi

    OBS_PYTHON=python3 bash .buildkite/upload_obs_artifacts.sh \
        --output "${ARCHIVE_DIR}/sandbox/obs-urls.txt" \
        --platform sandbox \
        --arch noarch \
        --channel "${obs_channel}" \
        "${version_args[@]}" \
        -- \
        "${HELM_DIR}"/*.tgz \
        "${MANIFEST_DIR}"/*.yaml \
        "${METADATA_DIR}"/*.json \
        "${METADATA_DIR}"/*.yaml \
        "${ARCHIVE_DIR}/index.html"
}

write_artifact_archive_html() {
    python3 - "${ARCHIVE_DIR}" "${SANDBOX_ARTIFACT_DIR}" "${BUILD_NUMBER}" "${BRANCH_NAME}" "${COMMIT_SHA}" <<'PY'
import html
import pathlib
import sys

archive_dir = pathlib.Path(sys.argv[1]).resolve()
build_number, branch_name, commit_sha = sys.argv[3:6]
index_path = archive_dir / "index.html"

def read_obs_urls():
    urls = []
    for obs_file in sorted(archive_dir.rglob("obs-urls.txt")):
        platform = obs_file.relative_to(archive_dir).parts[0]
        for line in obs_file.read_text(errors="replace").splitlines():
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            urls.append((platform, parts[0], parts[1]))
    return urls

rows = []
obs_urls = read_obs_urls()
if obs_urls:
    grouped = {}
    for platform, name, url in obs_urls:
        grouped.setdefault(platform, []).append((name, url))
    for platform in sorted(grouped):
        items = []
        for name, url in sorted(grouped[platform]):
            items.append(
                '<li>'
                f'<a href="{html.escape(url, quote=True)}">{html.escape(name)}</a>'
                '</li>'
            )
        rows.append(f"<section><h2>{html.escape(platform)} OBS links</h2><ul>{''.join(items)}</ul></section>")
else:
    rows.append("<section><h2>OBS links</h2><p>No OBS artifact URLs captured.</p></section>")

runtime_tags = []
for tag_file in sorted((archive_dir / "runtime-images").glob("*.txt")):
    for line in tag_file.read_text(errors="replace").splitlines():
        if line.strip():
            runtime_tags.append(line.strip())
if runtime_tags:
    items = [f"<li><code>{html.escape(tag)}</code></li>" for tag in sorted(set(runtime_tags))]
    rows.append(f"<section><h2>Runtime image tags</h2><ul>{''.join(items)}</ul></section>")

index_path.write_text(
    "<!doctype html>\n"
    "<html lang=\"en\">\n"
    "<head>\n"
    "  <meta charset=\"utf-8\">\n"
    "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
    "  <title>OpenYuanrong Build Artifacts</title>\n"
    "  <style>\n"
    "    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;color:#1f2933;background:#f7f8fa;}\n"
    "    header{background:#1f2933;color:white;padding:24px 32px;}\n"
    "    main{max-width:1040px;margin:0 auto;padding:24px 20px 40px;}\n"
    "    section{background:white;border:1px solid #d8dee4;border-radius:8px;margin:0 0 18px;padding:18px;}\n"
    "    h1{font-size:24px;margin:0 0 8px;} h2{font-size:18px;margin:0 0 12px;}\n"
    "    p{margin:0;color:#d0d7de;} ul{list-style:none;margin:0;padding:0;} li{padding:7px 0;border-top:1px solid #eef1f4;}\n"
    "    li:first-child{border-top:0;} a{color:#0969da;text-decoration:none;} a:hover{text-decoration:underline;}\n"
    "    code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;color:#344054;word-break:break-all;}\n"
    "  </style>\n"
    "</head>\n"
    "<body>\n"
    f"<header><h1>OpenYuanrong Build Artifacts</h1><p>Build #{html.escape(build_number)} · {html.escape(branch_name)} · {html.escape(commit_sha[:12])}</p></header>\n"
    f"<main>{''.join(rows)}</main>\n"
    "</body>\n"
    "</html>\n",
    encoding="utf-8",
)
PY
}

main() {
    mkdir -p "${HELM_DIR}" "${MANIFEST_DIR}" "${METADATA_DIR}" "${ARCHIVE_DIR}"

    require_bin "${DOCKER_BIN}"
    require_bin helm
    require_bin python3

    export DOCKER_CLI_EXPERIMENTAL="${DOCKER_CLI_EXPERIMENTAL:-enabled}"
    docker_login_if_configured

    local image_name
    for image_name in "${local_images[@]}"; do
        create_manifest "${image_name}"
    done

    local sdk_suffix
    while IFS= read -r sdk_suffix; do
        [ -n "${sdk_suffix}" ] || continue
        create_manifest "yr-runtime" "${IMAGE_TAG}-${sdk_suffix}" "-${sdk_suffix}"
    done < <(runtime_sdk_suffixes)

    write_values_override
    write_metadata

    helm lint "${CHART_DIR}" -f "${VALUES_FILE}" -f "${METADATA_DIR}/yr-k8s-image-values.yaml"
    helm template yr-k8s "${CHART_DIR}" \
        -f "${VALUES_FILE}" \
        -f "${METADATA_DIR}/yr-k8s-image-values.yaml" \
        >"${MANIFEST_DIR}/yr-k8s.yaml"
    helm package "${CHART_DIR}" \
        --version "${CHART_VERSION}" \
        --app-version "${APP_VERSION}" \
        --destination "${HELM_DIR}"

    collect_artifact_archive
    write_artifact_summary_json
    write_artifact_archive_html
    upload_manifest_artifacts_to_obs_if_configured

    if command -v buildkite-agent >/dev/null 2>&1; then
        buildkite-agent meta-data set "sandbox-release.${BUILDKITE_STEP_KEY}" "$(cat "${METADATA_DIR}/sandbox-release.json")"
        buildkite-agent artifact upload "${ARCHIVE_DIR}/index.html" || true
        buildkite-agent artifact upload "${METADATA_DIR}/build-artifacts.json" || true
        buildkite-agent annotate --style "success" --context "sandbox-manifest" \
            "Sandbox multi-arch manifests pushed with tag ${IMAGE_TAG}; Helm chart packaged as version ${CHART_VERSION}; build artifacts are summarized in artifacts/sandbox/archive/index.html and build-artifacts.json."
    fi
}

main "$@"
