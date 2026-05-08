#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

BUILD_STEP_KEY="${SANDBOX_BUILD_STEP_KEY:-build-all-amd64}"
PACKAGE_STEP_KEY="${SANDBOX_PACKAGE_STEP_KEY:-publish-sandbox-release-amd64}"
SANDBOX_METADATA="${ROOT_DIR}/artifacts/sandbox/metadata/sandbox-release.json"
RELEASE_ARTIFACT_DIR="${ROOT_DIR}/artifacts/release"
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
HELM_BIN="${HELM_BIN:-helm}"
KUBECONFIG_PATH="/var/run/yr-k8s/target/kubeconfig"
NAMESPACE="${YR_K8S_NAMESPACE:-yr}"
TRAEFIK_SERVICE="${YR_K8S_TRAEFIK_SERVICE:-yr-traefik}"
SMOKE_LOG_DIR="${ROOT_DIR}/artifacts/sandbox-smoke"
TOOL_DIR="${ROOT_DIR}/.buildkite/tools/bin"

host_arch() {
    case "$(uname -m)" in
        x86_64 | amd64) printf 'amd64\n' ;;
        aarch64 | arm64) printf 'arm64\n' ;;
        *)
            printf 'Unsupported architecture for CLI bootstrap: %s\n' "$(uname -m)" >&2
            exit 1
            ;;
    esac
}

download_file() {
    local url="$1"
    local output="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 300 --progress-bar \
            "${url}" -o "${output}"
    elif command -v wget >/dev/null 2>&1; then
        wget --timeout=30 --read-timeout=300 --tries=3 --progress=bar:force "${url}" -O "${output}"
    else
        printf 'Missing required downloader: curl or wget\n' >&2
        return 1
    fi
}

download_first() {
    local output="$1"
    shift
    local url
    for url in "$@"; do
        printf 'Downloading %s\n' "${url}" >&2
        if download_file "${url}" "${output}"; then
            return 0
        fi
        rm -f "${output}"
    done
    printf 'Failed to download any candidate for %s\n' "${output}" >&2
    exit 1
}

ensure_kubectl() {
    if command -v "${KUBECTL_BIN}" >/dev/null 2>&1; then
        KUBECTL_BIN="$(command -v "${KUBECTL_BIN}")"
        return 0
    fi

    local arch
    local version
    mkdir -p "${TOOL_DIR}"
    arch="$(host_arch)"
    version="${KUBECTL_VERSION:-v1.30.8}"
    KUBECTL_BIN="${TOOL_DIR}/kubectl"
    printf 'Installing kubectl %s for linux/%s\n' "${version}" "${arch}" >&2
    download_first "${KUBECTL_BIN}" \
        "${KUBECTL_DOWNLOAD_URL:-https://dl.k8s.io/release/${version}/bin/linux/${arch}/kubectl}" \
        "https://cdn.dl.k8s.io/release/${version}/bin/linux/${arch}/kubectl"
    chmod +x "${KUBECTL_BIN}"
}

ensure_helm() {
    if command -v "${HELM_BIN}" >/dev/null 2>&1; then
        HELM_BIN="$(command -v "${HELM_BIN}")"
        return 0
    fi

    local arch
    local version
    local tmp_dir
    mkdir -p "${TOOL_DIR}"
    arch="$(host_arch)"
    version="${HELM_VERSION:-v3.15.4}"
    tmp_dir="$(mktemp -d)"
    printf 'Installing helm %s for linux/%s\n' "${version}" "${arch}" >&2
    download_first "${tmp_dir}/helm.tar.gz" \
        "${HELM_DOWNLOAD_URL:-https://get.helm.sh/helm-${version}-linux-${arch}.tar.gz}"
    tar -xzf "${tmp_dir}/helm.tar.gz" -C "${tmp_dir}"
    mv "${tmp_dir}/linux-${arch}/helm" "${TOOL_DIR}/helm"
    rm -rf "${tmp_dir}"
    HELM_BIN="${TOOL_DIR}/helm"
    chmod +x "${HELM_BIN}"
}

require_bin() {
    local bin_name="$1"
    if ! command -v "${bin_name}" >/dev/null 2>&1; then
        printf 'Missing required CLI: %s\n' "${bin_name}" >&2
        exit 1
    fi
}

download_artifacts() {
    mkdir -p "${RELEASE_ARTIFACT_DIR}" "$(dirname "${SANDBOX_METADATA}")"
    if command -v buildkite-agent >/dev/null 2>&1; then
        buildkite-agent artifact download "artifacts/sandbox/metadata/sandbox-release.json" . --step "${PACKAGE_STEP_KEY}"
        buildkite-agent artifact download "artifacts/release/openyuanrong-*.whl" . --step "${BUILD_STEP_KEY}"
        buildkite-agent artifact download "artifacts/release/openyuanrong_sdk*.whl" . --step "${BUILD_STEP_KEY}"
    fi
    if [ ! -f "${SANDBOX_METADATA}" ]; then
        printf 'Missing sandbox metadata artifact: %s\n' "${SANDBOX_METADATA}" >&2
        exit 1
    fi
}

json_field() {
    local field_name="$1"
    python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "${SANDBOX_METADATA}" "${field_name}"
}

resolve_smoke_python() {
    local sdk_wheel="$1"
    local wheel_name
    local python_minor
    local candidate
    wheel_name="$(basename "${sdk_wheel}")"

    case "${wheel_name}" in
        *-cp39-*) python_minor="3.9" ;;
        *-cp310-*) python_minor="3.10" ;;
        *-cp311-*) python_minor="3.11" ;;
        *) python_minor="" ;;
    esac

    if [ -n "${YR_K8S_SMOKE_PYTHON:-}" ]; then
        printf '%s\n' "${YR_K8S_SMOKE_PYTHON}"
        return 0
    fi
    if [ -n "${python_minor}" ]; then
        for candidate in "/opt/buildtools/python${python_minor}/bin/python${python_minor}" "python${python_minor}"; do
            if command -v "${candidate}" >/dev/null 2>&1; then
                command -v "${candidate}"
                return 0
            fi
        done
    fi
    command -v python3
}

install_smoke_wheels() {
    local sdk_wheel
    local core_wheel
    local pip_index_url
    local pip_trusted_host
    local -a pip_args
    sdk_wheel="$(find "${RELEASE_ARTIFACT_DIR}" -maxdepth 1 -type f -name 'openyuanrong_sdk*.whl' | sort -V | tail -1)"
    core_wheel="$(find "${RELEASE_ARTIFACT_DIR}" -maxdepth 1 -type f -name 'openyuanrong-*.whl' | sort -V | tail -1)"
    if [ -z "${sdk_wheel}" ] || [ -z "${core_wheel}" ]; then
        printf 'Missing smoke wheels under %s\n' "${RELEASE_ARTIFACT_DIR}" >&2
        exit 1
    fi

    SMOKE_PYTHON="$(resolve_smoke_python "${sdk_wheel}")"
    export SMOKE_PYTHON
    pip_index_url="${YR_K8S_SMOKE_PIP_INDEX_URL:-https://repo.huaweicloud.com/repository/pypi/simple}"
    pip_trusted_host="${YR_K8S_SMOKE_PIP_TRUSTED_HOST:-repo.huaweicloud.com}"
    pip_args=(--force-reinstall)
    if [ -n "${pip_index_url}" ]; then
        pip_args+=(--index-url "${pip_index_url}")
    fi
    if [ -n "${pip_trusted_host}" ]; then
        pip_args+=(--trusted-host "${pip_trusted_host}")
    fi
    PIP_BREAK_SYSTEM_PACKAGES=1 "${SMOKE_PYTHON}" -m pip install "${pip_args[@]}" "${sdk_wheel}" "${core_wheel}" pytest
}

wait_for_traefik_address() {
    local timeout="${YR_K8S_ADDRESS_TIMEOUT:-300}"
    local deadline=$((SECONDS + timeout))
    local address
    while [ "${SECONDS}" -le "${deadline}" ]; do
        address="$("${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" get svc "${TRAEFIK_SERVICE}" -o json \
            | python3 -c '
import json
import sys

svc = json.load(sys.stdin)
ingress = svc.get("status", {}).get("loadBalancer", {}).get("ingress", [])
hosts = [item.get("ip") or item.get("hostname") for item in ingress]
hosts = [host for host in hosts if host]
public_hosts = [host for host in hosts if not host.startswith(("10.", "172.", "192.168."))]
host = (public_hosts or hosts or [""])[0]
ports = svc.get("spec", {}).get("ports", [])
port = next((item["port"] for item in ports if item.get("name") == "frontend-direct"), "")
if host and port:
    print(f"{host}:{port}")
')" || true
        if [ -n "${address}" ]; then
            printf '%s\n' "${address}"
            return 0
        fi
        sleep 5
    done
    printf 'Timed out waiting for %s/%s LoadBalancer address.\n' "${NAMESPACE}" "${TRAEFIK_SERVICE}" >&2
    exit 1
}

run_smoke() {
    local server_address="$1"
    local -a pytest_args
    mkdir -p "${SMOKE_LOG_DIR}"
    install_smoke_wheels

    if [ -n "${YR_K8S_SMOKE_PYTEST_ARGS:-}" ]; then
        read -r -a pytest_args <<<"${YR_K8S_SMOKE_PYTEST_ARGS}"
    else
        pytest_args=(-m smoke)
    fi

    printf 'Running yr-k8s off-cluster smoke against %s with %s\n' "${server_address}" "${SMOKE_PYTHON}" >&2
    YR_ENABLE_TLS="${YR_ENABLE_TLS:-false}" \
    YR_LOG_LEVEL="${YR_K8S_SMOKE_LOG_LEVEL:-INFO}" \
    bash test/st/run_off_cluster_test.sh -a "${server_address}" -p "${SMOKE_PYTHON}" -- "${pytest_args[@]}" \
        2>&1 | tee "${SMOKE_LOG_DIR}/smoke.log"
}

main() {
    ensure_kubectl
    ensure_helm
    export PATH="${TOOL_DIR}:${PATH}"

    require_bin "${KUBECTL_BIN}"
    require_bin "${HELM_BIN}"
    require_bin python3

    if [ ! -f "${KUBECONFIG_PATH}" ]; then
        printf 'Missing target kubeconfig: %s\n' "${KUBECONFIG_PATH}" >&2
        exit 1
    fi

    download_artifacts
    export YR_K8S_KUBECONFIG="${KUBECONFIG_PATH}"
    export YR_K8S_IMAGE_TAG="${YR_K8S_IMAGE_TAG:-$(json_field image_tag)}"
    export YR_K8S_REGISTRY_REPO="${YR_K8S_REGISTRY_REPO:-$(json_field registry)}"
    export HELM_BIN

    bash deploy/sandbox/k8s/deploy.sh

    if [[ "${YR_K8S_RUN_SMOKE:-true}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
        run_smoke "${YR_K8S_SMOKE_SERVER_ADDRESS:-$(wait_for_traefik_address)}"
    fi

    if command -v buildkite-agent >/dev/null 2>&1; then
        buildkite-agent artifact upload "${SMOKE_LOG_DIR}/**/*" || true
        buildkite-agent annotate --style "success" --context "sandbox-k8s" \
            "Deployed sandbox image tag ${YR_K8S_IMAGE_TAG} to the target K8S cluster and ran smoke checks."
    fi
}

main "$@"
