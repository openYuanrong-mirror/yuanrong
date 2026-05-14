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
LINUX_AMD64_SDK_STEPS="${SANDBOX_AMD64_SDK_STEPS:-build-sdk-amd64-cp39 build-sdk-amd64-cp310 build-sdk-amd64-cp311 build-sdk-amd64-cp312}"
LINUX_ARM64_SDK_STEPS="${SANDBOX_ARM64_SDK_STEPS:-build-sdk-arm64-cp39 build-sdk-arm64-cp310 build-sdk-arm64-cp311 build-sdk-arm64-cp312}"
MACOS_ARM64_SDK_STEPS="${SANDBOX_MACOS_ARM64_SDK_STEPS:-build-sdk-macos-arm64-cp39 build-sdk-macos-arm64-cp310 build-sdk-macos-arm64-cp311 build-sdk-macos-arm64-cp312}"
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
        "${ARCHIVE_DIR}/runtime-images"

    if ! command -v buildkite-agent >/dev/null 2>&1; then
        return 0
    fi

    buildkite-agent artifact download "artifacts/release/*" "${ARCHIVE_DIR}/linux-amd64" \
        --step "build-all-amd64" || true
    for step_key in ${LINUX_AMD64_SDK_STEPS}; do
        buildkite-agent artifact download "artifacts/openyuanrong-sdk/*" "${ARCHIVE_DIR}/linux-amd64-sdk" \
            --step "${step_key}" || true
    done
    buildkite-agent artifact download "artifacts/release/*" "${ARCHIVE_DIR}/linux-arm64" \
        --step "build-all-arm64" || true
    for step_key in ${LINUX_ARM64_SDK_STEPS}; do
        buildkite-agent artifact download "artifacts/openyuanrong-sdk/*" "${ARCHIVE_DIR}/linux-arm64-sdk" \
            --step "${step_key}" || true
    done
    for step_key in ${MACOS_ARM64_SDK_STEPS}; do
        buildkite-agent artifact download "artifacts/openyuanrong-sdk/*" "${ARCHIVE_DIR}/macos-arm64-sdk" \
            --step "${step_key}" || true
    done
    for step_key in ${RUNTIME_IMAGE_STEPS}; do
        buildkite-agent artifact download "artifacts/sandbox/runtime-images/*" "${ARCHIVE_DIR}/runtime-images" \
            --step "${step_key}" || true
    done
}

write_artifact_archive_html() {
    python3 - "${ARCHIVE_DIR}" "${SANDBOX_ARTIFACT_DIR}" "${BUILD_NUMBER}" "${BRANCH_NAME}" "${COMMIT_SHA}" <<'PY'
import html
import os
import pathlib
import sys

archive_dir = pathlib.Path(sys.argv[1]).resolve()
sandbox_dir = pathlib.Path(sys.argv[2]).resolve()
build_number, branch_name, commit_sha = sys.argv[3:6]
index_path = archive_dir / "index.html"

sections = [
    ("Linux x86_64 release artifacts", archive_dir / "linux-amd64"),
    ("Linux x86_64 SDK artifacts", archive_dir / "linux-amd64-sdk"),
    ("Linux arm64 release artifacts", archive_dir / "linux-arm64"),
    ("Linux arm64 SDK artifacts", archive_dir / "linux-arm64-sdk"),
    ("macOS arm64 SDK artifacts", archive_dir / "macos-arm64-sdk"),
    ("Runtime image tags", archive_dir / "runtime-images"),
    ("Sandbox manifests and Helm artifacts", sandbox_dir),
]

def rel_link(path: pathlib.Path) -> str:
    return pathlib.Path(os.path.relpath(path, archive_dir)).as_posix()

def display_name(path: pathlib.Path, base: pathlib.Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.name

def iter_files(base: pathlib.Path):
    if not base.exists():
        return []
    files = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if path.resolve() == index_path:
            continue
        if base == sandbox_dir and archive_dir in path.resolve().parents:
            continue
        files.append(path)
    return files

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
for title, base in sections:
    files = iter_files(base)
    if not files:
        rows.append(f"<section><h2>{html.escape(title)}</h2><p>No artifacts captured.</p></section>")
        continue
    items = []
    for path in files:
        href = html.escape(rel_link(path), quote=True)
        label = html.escape(display_name(path, base))
        size = path.stat().st_size
        items.append(f'<li><a href="{href}">{label}</a> <span>{size:,} bytes</span></li>')
    rows.append(f"<section><h2>{html.escape(title)}</h2><ul>{''.join(items)}</ul></section>")

obs_urls = read_obs_urls()
if obs_urls:
    items = []
    for platform, name, url in obs_urls:
        items.append(
            '<li>'
            f'<span>{html.escape(platform)}</span> '
            f'<a href="{html.escape(url, quote=True)}">{html.escape(name)}</a>'
            '</li>'
        )
    rows.append(f"<section><h2>OBS links</h2><ul>{''.join(items)}</ul></section>")

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
    "    span{color:#667085;font-size:13px;margin-left:8px;}\n"
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
    write_artifact_archive_html

    if command -v buildkite-agent >/dev/null 2>&1; then
        buildkite-agent artifact upload "${SANDBOX_ARTIFACT_DIR}/**/*" || true
        buildkite-agent annotate --style "success" --context "sandbox-manifest" \
            "Sandbox multi-arch manifests pushed with tag ${IMAGE_TAG}; Helm chart packaged as version ${CHART_VERSION}; artifact archive: artifacts/sandbox/archive/index.html."
    fi
}

main "$@"
