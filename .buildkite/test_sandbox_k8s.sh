#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

BUILD_STEP_KEY="${SANDBOX_BUILD_STEP_KEY:-build-all-amd64}"
PACKAGE_STEP_KEY="${SANDBOX_PACKAGE_STEP_KEY:-publish-sandbox-release-amd64}"
SDK_STEP_KEY="${SANDBOX_SDK_STEP_KEY:-build-sdk-amd64-cp311}"
SMOKE_SDK_WHEEL_PATTERN="${YR_K8S_SMOKE_SDK_WHEEL_PATTERN:-openyuanrong_sdk*-cp311-*.whl}"
DEFAULT_SMOKE_CONTROLPLANE_WHEEL_PATTERNS="openyuanrong-*.whl openyuanrong_runtime-*.whl openyuanrong_faas-*.whl openyuanrong_dashboard-*.whl openyuanrong_cpp_sdk-*.whl openyuanrong_functionsystem-*.whl openyuanrong_datasystem-*.whl"
SMOKE_CONTROLPLANE_WHEEL_PATTERNS="${YR_K8S_SMOKE_CONTROLPLANE_WHEEL_PATTERNS:-${DEFAULT_SMOKE_CONTROLPLANE_WHEEL_PATTERNS}}"
SANDBOX_METADATA="${ROOT_DIR}/artifacts/sandbox/metadata/sandbox-release.json"
RELEASE_ARTIFACT_DIR="${ROOT_DIR}/artifacts/release"
SDK_ARTIFACT_DIR="${ROOT_DIR}/artifacts/openyuanrong-sdk"
OBS_URL_DIR="${ROOT_DIR}/artifacts/obs-urls"
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
HELM_BIN="${HELM_BIN:-helm}"
KUBECONFIG_PATH="/var/run/yr-k8s/target/kubeconfig"
NAMESPACE="${YR_K8S_NAMESPACE:-yr}"
TRAEFIK_SERVICE="${YR_K8S_TRAEFIK_SERVICE:-yr-traefik}"
SMOKE_LOG_DIR="${ROOT_DIR}/artifacts/sandbox-smoke"
TOOL_DIR="${ROOT_DIR}/.buildkite/tools/bin"
TRAEFIK_PORT_FORWARD_ADDRESS="${YR_K8S_TRAEFIK_PORT_FORWARD_ADDRESS:-127.0.0.1}"
TRAEFIK_PORT_FORWARD_PORT="${YR_K8S_TRAEFIK_PORT_FORWARD_PORT:-18888}"
TRAEFIK_PORT_FORWARD_TARGET_PORT="${YR_K8S_TRAEFIK_PORT_FORWARD_TARGET_PORT:-18888}"
TRAEFIK_PORT_FORWARD_EXTRA_PORTS="${YR_K8S_TRAEFIK_PORT_FORWARD_EXTRA_PORTS:-8888:8888}"
TRAEFIK_GATEWAY_PORT="${YR_K8S_TRAEFIK_GATEWAY_PORT:-8888}"
PORT_FORWARD_PID=""
TRAEFIK_PORT_FORWARD_SERVER_ADDRESS=""
TRAEFIK_GATEWAY_ADDRESS=""

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

read_smoke_controlplane_wheel_patterns() {
    read -r -a SMOKE_CONTROLPLANE_WHEEL_PATTERN_LIST <<<"${SMOKE_CONTROLPLANE_WHEEL_PATTERNS}"
}

download_obs_patterns() {
    local urls_root="$1"
    local output_dir="$2"
    shift 2

    local pattern
    for pattern in "$@"; do
        python3 .buildkite/download_obs_artifacts.py \
            --urls-root "${urls_root}" \
            --output-dir "${output_dir}" \
            --pattern "${pattern}"
    done
}

resolve_single_wheel() {
    local pattern="$1"
    local matches=()

    mapfile -t matches < <(find "${RELEASE_ARTIFACT_DIR}" -maxdepth 1 -type f -name "${pattern}" -print | sort -V)
    if [ "${#matches[@]}" -eq 0 ]; then
        printf 'Missing smoke wheel matching %s under %s\n' "${pattern}" "${RELEASE_ARTIFACT_DIR}" >&2
        exit 1
    fi
    if [ "${#matches[@]}" -ne 1 ]; then
        printf 'Expected exactly one smoke wheel matching %s under %s, found %s\n' \
            "${pattern}" "${RELEASE_ARTIFACT_DIR}" "${#matches[@]}" >&2
        printf '%s\n' "${matches[@]}" >&2
        exit 1
    fi
    printf '%s\n' "${matches[0]}"
}

download_artifacts() {
    mkdir -p "${RELEASE_ARTIFACT_DIR}" "${SDK_ARTIFACT_DIR}" "${OBS_URL_DIR}" "$(dirname "${SANDBOX_METADATA}")"
    read_smoke_controlplane_wheel_patterns
    if command -v buildkite-agent >/dev/null 2>&1; then
        buildkite-agent meta-data get "sandbox-release.${PACKAGE_STEP_KEY}" >"${SANDBOX_METADATA}"
        mkdir -p "${OBS_URL_DIR}/${BUILD_STEP_KEY}" "${OBS_URL_DIR}/${SDK_STEP_KEY}"
        buildkite-agent meta-data get "obs-urls.${BUILD_STEP_KEY}" \
            >"${OBS_URL_DIR}/${BUILD_STEP_KEY}/obs-urls.txt"
        buildkite-agent meta-data get "obs-urls.${SDK_STEP_KEY}" \
            >"${OBS_URL_DIR}/${SDK_STEP_KEY}/obs-urls.txt"
        download_obs_patterns \
            "${OBS_URL_DIR}/${BUILD_STEP_KEY}" \
            "${RELEASE_ARTIFACT_DIR}" \
            "${SMOKE_CONTROLPLANE_WHEEL_PATTERN_LIST[@]}"
        python3 .buildkite/download_obs_artifacts.py \
            --urls-root "${OBS_URL_DIR}/${SDK_STEP_KEY}" \
            --output-dir "${SDK_ARTIFACT_DIR}" \
            --pattern "${SMOKE_SDK_WHEEL_PATTERN}"
    fi
    if compgen -G "${SDK_ARTIFACT_DIR}/${SMOKE_SDK_WHEEL_PATTERN}" >/dev/null; then
        cp -af "${SDK_ARTIFACT_DIR}"/${SMOKE_SDK_WHEEL_PATTERN} "${RELEASE_ARTIFACT_DIR}/"
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

runtime_image_tag() {
    python3 -c '
import json
import sys

metadata = json.load(open(sys.argv[1]))
image_tag = metadata["image_tag"]
for image in metadata.get("images", []):
    if "/yr-runtime:" in image:
        print(image.rsplit(":", 1)[1])
        break
else:
    print(f"{image_tag}-cp310")
' "${SANDBOX_METADATA}"
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
        *-cp312-*) python_minor="3.12" ;;
        *-cp313-*) python_minor="3.13" ;;
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
    local pip_index_url
    local pip_trusted_host
    local -a pip_args
    local -a smoke_wheels
    local pattern
    sdk_wheel="$(find "${RELEASE_ARTIFACT_DIR}" -maxdepth 1 -type f -name "${SMOKE_SDK_WHEEL_PATTERN}" | sort -V | tail -1)"
    if [ -z "${sdk_wheel}" ]; then
        printf 'Missing smoke wheels under %s\n' "${RELEASE_ARTIFACT_DIR}" >&2
        exit 1
    fi
    read_smoke_controlplane_wheel_patterns
    for pattern in "${SMOKE_CONTROLPLANE_WHEEL_PATTERN_LIST[@]}"; do
        smoke_wheels+=("$(resolve_single_wheel "${pattern}")")
    done
    smoke_wheels+=("${sdk_wheel}")

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
    PIP_BREAK_SYSTEM_PACKAGES=1 "${SMOKE_PYTHON}" -m pip install "${pip_args[@]}" "${smoke_wheels[@]}" pytest
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

cleanup_port_forward() {
    if [ -n "${PORT_FORWARD_PID}" ] && kill -0 "${PORT_FORWARD_PID}" >/dev/null 2>&1; then
        kill "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
        wait "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
    fi
}

cleanup_node_docker_cache() {
    local enabled="${YR_K8S_CLEAN_NODE_DOCKER_CACHE:-true}"
    local pods pod

    if [[ ! "${enabled}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
        printf 'Skipping yr-node Docker cache cleanup because YR_K8S_CLEAN_NODE_DOCKER_CACHE=%s.\n' \
            "${enabled}" >&2
        return 0
    fi
    if [ ! -f "${KUBECONFIG_PATH}" ]; then
        return 0
    fi

    printf 'Cleaning yr-node private Docker cache in %s namespace.\n' "${NAMESPACE}" >&2
    mapfile -t pods < <(
        "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" get pods \
            -l app.kubernetes.io/component=node \
            -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true
    )
    for pod in "${pods[@]}"; do
        [ -n "${pod}" ] || continue
        printf 'Pruning Docker cache in pod/%s.\n' "${pod}" >&2
        "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" exec "${pod}" -c node -- sh -lc '
            set +e
            if command -v docker >/dev/null 2>&1; then
                docker container prune -f
                docker image prune -af
                docker builder prune -af
                docker system df
            fi
            find /var/lib/docker/containers -type f -name "*-json.log" \
                -exec sh -c '"'"'for f do : > "$f" || true; done'"'"' sh {} + 2>/dev/null
            true
        ' || true
    done
}

cleanup_k8s_node_image_cache() {
    local enabled="${YR_K8S_CLEAN_K8S_NODE_IMAGE_CACHE:-true}"
    local image="${YR_K8S_NODE_CACHE_CLEANUP_IMAGE:-swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev/busybox:1.36}"
    local nodes node pod

    if [[ ! "${enabled}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
        printf 'Skipping K8S node image cache cleanup because YR_K8S_CLEAN_K8S_NODE_IMAGE_CACHE=%s.\n' \
            "${enabled}" >&2
        return 0
    fi
    if [ ! -f "${KUBECONFIG_PATH}" ]; then
        return 0
    fi

    mapfile -t nodes < <(
        "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" get nodes \
            -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true
    )
    for node in "${nodes[@]}"; do
        [ -n "${node}" ] || continue
        pod="yr-node-cache-cleanup-${node//./-}"
        printf 'Pruning unused containerd images on node/%s.\n' "${node}" >&2
        "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" delete pod "${pod}" \
            --ignore-not-found >/dev/null 2>&1 || true
        cat <<EOF | "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: ${pod}
spec:
  nodeName: ${node}
  hostPID: true
  restartPolicy: Never
  containers:
  - name: cleanup
    image: ${image}
    command: ["sh", "-lc", "sleep 1800"]
    securityContext:
      privileged: true
    volumeMounts:
    - name: host-root
      mountPath: /host
  volumes:
  - name: host-root
    hostPath:
      path: /
      type: Directory
EOF
        if "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" wait \
            --for=condition=Ready "pod/${pod}" --timeout="${YR_K8S_NODE_CACHE_CLEANUP_READY_TIMEOUT:-120s}"; then
            "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" exec "${pod}" -- sh -lc '
                chroot /host sh -lc '"'"'
                    set +e
                    df -h /var/lib/containerd /var/lib/kubelet 2>/dev/null || df -h /
                    if command -v crictl >/dev/null 2>&1; then
                        crictl --runtime-endpoint unix:///run/containerd/containerd.sock \
                            --image-endpoint unix:///run/containerd/containerd.sock rmi --prune
                    elif command -v ctr >/dev/null 2>&1; then
                        ctr -n k8s.io images prune --all
                    fi
                    df -h /var/lib/containerd /var/lib/kubelet 2>/dev/null || df -h /
                    true
                '"'"'
            ' || true
        else
            "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" describe "pod/${pod}" >&2 || true
        fi
        "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" delete pod "${pod}" \
            --ignore-not-found >/dev/null 2>&1 || true
    done
}

cleanup() {
    local status="$?"
    cleanup_port_forward
    cleanup_node_docker_cache
    cleanup_k8s_node_image_cache
    return "${status}"
}

wait_for_local_port() {
    local host="$1"
    local port="$2"
    local timeout="${3:-60}"
    python3 - "${host}" "${port}" "${timeout}" <<'PY'
import socket
import sys
import time

host = sys.argv[1]
port = int(sys.argv[2])
deadline = time.time() + int(sys.argv[3])
last_error = None
while time.time() <= deadline:
    try:
        with socket.create_connection((host, port), timeout=2):
            sys.exit(0)
    except OSError as exc:
        last_error = exc
        time.sleep(1)
print(f"Timed out waiting for {host}:{port}: {last_error}", file=sys.stderr)
sys.exit(1)
PY
}

start_traefik_port_forward() {
    local log_file="${SMOKE_LOG_DIR}/traefik-port-forward.log"
    local -a port_mappings
    local -a extra_port_mappings
    local mapping
    local local_port
    mkdir -p "${SMOKE_LOG_DIR}"

    port_mappings=("${TRAEFIK_PORT_FORWARD_PORT}:${TRAEFIK_PORT_FORWARD_TARGET_PORT}")
    if [ -n "${TRAEFIK_PORT_FORWARD_EXTRA_PORTS}" ]; then
        read -r -a extra_port_mappings <<<"${TRAEFIK_PORT_FORWARD_EXTRA_PORTS}"
        port_mappings+=("${extra_port_mappings[@]}")
    fi

    printf 'Starting port-forward %s/%s --address %s %s\n' \
        "${NAMESPACE}" "${TRAEFIK_SERVICE}" \
        "${TRAEFIK_PORT_FORWARD_ADDRESS}" "${port_mappings[*]}" >&2
    "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" port-forward \
        --address "${TRAEFIK_PORT_FORWARD_ADDRESS}" \
        "svc/${TRAEFIK_SERVICE}" \
        "${port_mappings[@]}" \
        >"${log_file}" 2>&1 &
    PORT_FORWARD_PID="$!"

    for mapping in "${port_mappings[@]}"; do
        local_port="${mapping%%:*}"
        if ! wait_for_local_port "${TRAEFIK_PORT_FORWARD_ADDRESS}" "${local_port}" \
            "${YR_K8S_PORT_FORWARD_TIMEOUT:-60}"; then
            tail -n 120 "${log_file}" >&2 || true
            return 1
        fi
    done
    TRAEFIK_PORT_FORWARD_SERVER_ADDRESS="${TRAEFIK_PORT_FORWARD_ADDRESS}:${TRAEFIK_PORT_FORWARD_PORT}"
    TRAEFIK_GATEWAY_ADDRESS="${TRAEFIK_PORT_FORWARD_ADDRESS}:${TRAEFIK_GATEWAY_PORT}"
}

wait_for_smoke_ready() {
    local server_address="$1"
    local timeout="${YR_K8S_SMOKE_READY_TIMEOUT:-600}"
    local deadline=$((SECONDS + timeout))
    local attempt=1

    printf 'Waiting for yr-k8s smoke readiness against %s\n' "${server_address}" >&2
    while [ "${SECONDS}" -le "${deadline}" ]; do
        if YR_ENABLE_TLS="${YR_ENABLE_TLS:-false}" \
            YR_SERVER_ADDRESS="${server_address}" \
            YR_LOG_LEVEL="${YR_K8S_SMOKE_LOG_LEVEL:-INFO}" \
            YR_K8S_SMOKE_TIMEOUT="${YR_K8S_SMOKE_READY_OPERATION_TIMEOUT:-120}" \
            "${SMOKE_PYTHON}" deploy/sandbox/k8s/smoke.py \
            >"${SMOKE_LOG_DIR}/ready-${attempt}.log" 2>&1; then
            printf 'yr-k8s smoke readiness check passed on attempt %s.\n' "${attempt}" >&2
            return 0
        fi
        printf 'yr-k8s smoke readiness attempt %s failed; retrying in 15s.\n' "${attempt}" >&2
        tail -n 80 "${SMOKE_LOG_DIR}/ready-${attempt}.log" >&2 || true
        sleep 15
        attempt=$((attempt + 1))
    done

    printf 'Timed out waiting for yr-k8s smoke readiness after %ss.\n' "${timeout}" >&2
    return 1
}

run_smoke() {
    local server_address="$1"
    local -a pytest_args
    mkdir -p "${SMOKE_LOG_DIR}"
    install_smoke_wheels
    wait_for_smoke_ready "${server_address}"

    if [ -n "${YR_K8S_SMOKE_PYTEST_ARGS:-}" ]; then
        read -r -a pytest_args <<<"${YR_K8S_SMOKE_PYTEST_ARGS}"
    else
        pytest_args=(-m smoke)
    fi

    local gateway_address="${YR_K8S_TRAEFIK_GATEWAY_ADDRESS:-${TRAEFIK_GATEWAY_ADDRESS}}"
    if [ -z "${gateway_address}" ]; then
        gateway_address="${TRAEFIK_PORT_FORWARD_ADDRESS}:${TRAEFIK_GATEWAY_PORT}"
    fi
    printf 'Running yr-k8s off-cluster smoke against %s (gateway %s) with %s\n' \
        "${server_address}" "${gateway_address}" "${SMOKE_PYTHON}" >&2
    YR_ENABLE_TLS="${YR_ENABLE_TLS:-false}" \
    YR_GATEWAY_ADDRESS="${gateway_address}" \
    YR_OFF_CLUSTER_WHEEL_DIR="${RELEASE_ARTIFACT_DIR}" \
    YR_OFF_CLUSTER_USE_UV_VENV=false \
    YR_OFF_CLUSTER_TEST_TIMEOUT="${YR_OFF_CLUSTER_TEST_TIMEOUT:-1200}" \
    UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-300}" \
    YR_LOG_LEVEL="${YR_K8S_SMOKE_LOG_LEVEL:-INFO}" \
    bash test/st/run_off_cluster_test.sh -a "${server_address}" --no-uv-venv -p "${SMOKE_PYTHON}" -- "${pytest_args[@]}" \
        2>&1 | tee "${SMOKE_LOG_DIR}/smoke.log"
}

main() {
    ensure_kubectl
    ensure_helm
    export PATH="${TOOL_DIR}:${PATH}"
    trap cleanup EXIT

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
    export YR_K8S_RUNTIME_IMAGE_TAG="${YR_K8S_RUNTIME_IMAGE_TAG:-$(runtime_image_tag)}"
    export YR_K8S_RUNTIME_IMAGE_TAG_CP39="${YR_K8S_RUNTIME_IMAGE_TAG_CP39:-${YR_K8S_IMAGE_TAG}-cp39}"
    export YR_K8S_RUNTIME_IMAGE_TAG_CP310="${YR_K8S_RUNTIME_IMAGE_TAG_CP310:-${YR_K8S_RUNTIME_IMAGE_TAG}}"
    export YR_K8S_RUNTIME_IMAGE_TAG_CP311="${YR_K8S_RUNTIME_IMAGE_TAG_CP311:-${YR_K8S_IMAGE_TAG}-cp311}"
    export YR_K8S_RUNTIME_IMAGE_TAG_CP312="${YR_K8S_RUNTIME_IMAGE_TAG_CP312:-${YR_K8S_IMAGE_TAG}-cp312}"
    export YR_K8S_REGISTRY_REPO="${YR_K8S_REGISTRY_REPO:-$(json_field registry)}"
    export HELM_BIN
    if [[ "${YR_K8S_SMOKE_ENABLE_EVENT:-true}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
        export YR_K8S_EXTRA_VALUES_FILE="${ROOT_DIR}/deploy/sandbox/k8s/k8s/values.buildkite-smoke.yaml"
    else
        unset YR_K8S_EXTRA_VALUES_FILE
    fi

    bash deploy/sandbox/k8s/deploy.sh

    if [[ "${YR_K8S_RUN_SMOKE:-true}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
        local server_address
        if [ -n "${YR_K8S_SMOKE_SERVER_ADDRESS:-}" ]; then
            server_address="${YR_K8S_SMOKE_SERVER_ADDRESS}"
        else
            start_traefik_port_forward
            server_address="${TRAEFIK_PORT_FORWARD_SERVER_ADDRESS}"
        fi
        run_smoke "${server_address}"
    fi

    if command -v buildkite-agent >/dev/null 2>&1; then
        buildkite-agent annotate --style "success" --context "sandbox-k8s" \
            "Deployed sandbox image tag ${YR_K8S_IMAGE_TAG} to the target K8S cluster and ran smoke checks."
    fi
}

main "$@"
