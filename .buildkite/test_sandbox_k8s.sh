#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

BUILD_STEP_KEY="${SANDBOX_BUILD_STEP_KEY:-build-all-amd64}"
SDK_STEP_KEY="${SANDBOX_SDK_STEP_KEY:-build-sdk-amd64-cp311}"
PACKAGE_STEP_KEY="${SANDBOX_PACKAGE_STEP_KEY:-publish-sandbox-release-amd64}"
SOURCE_BUILD_ID="${YR_K8S_SOURCE_BUILD_ID:-}"
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
RELEASE_NAME="${YR_K8S_RELEASE:-yr-k8s}"
EDGE_SERVICE="${YR_K8S_EDGE_SERVICE:-yr-edge-frontend}"
SMOKE_LOG_DIR="${ROOT_DIR}/artifacts/sandbox-smoke"
EDGE_TLS_CA_FILE="${YR_K8S_EDGE_TLS_CA_FILE:-${SMOKE_LOG_DIR}/edge-tls-ca.crt}"
TOOL_DIR="${ROOT_DIR}/.buildkite/tools/bin"
PORT_FORWARD_ADDRESS="${YR_K8S_PORT_FORWARD_ADDRESS:-127.0.0.1}"
EDGE_TLS_PORT="${YR_K8S_EDGE_TLS_PORT:-8443}"
EDGE_PLAIN_PORT="${YR_K8S_EDGE_PLAIN_PORT:-8080}"
EDGE_TLS_ADDRESS="${YR_K8S_EDGE_TLS_ADDRESS:-${PORT_FORWARD_ADDRESS}:${EDGE_TLS_PORT}}"
EDGE_PLAIN_ADDRESS="${YR_K8S_EDGE_PLAIN_ADDRESS:-${PORT_FORWARD_ADDRESS}:${EDGE_PLAIN_PORT}}"
SMOKE_SERVER_TLS="${YR_K8S_SMOKE_SERVER_TLS:-true}"
PORT_FORWARD_PIDS=()
USING_LOCAL_PORT_FORWARDS=false

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

buildkite_metadata_get() {
	local key="$1"
	if [ -n "${YR_K8S_SOURCE_BUILD_ID:-}" ]; then
		buildkite-agent meta-data get "${key}" --build "${YR_K8S_SOURCE_BUILD_ID}"
	else
		buildkite-agent meta-data get "${key}"
	fi
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
		buildkite_metadata_get "sandbox-release.${PACKAGE_STEP_KEY}" >"${SANDBOX_METADATA}"
		mkdir -p "${OBS_URL_DIR}/${BUILD_STEP_KEY}" "${OBS_URL_DIR}/${SDK_STEP_KEY}"
		buildkite_metadata_get "obs-urls.${BUILD_STEP_KEY}" \
			>"${OBS_URL_DIR}/${BUILD_STEP_KEY}/obs-urls.txt"
		buildkite_metadata_get "obs-urls.${SDK_STEP_KEY}" \
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

json_optional_field() {
	local field_name="$1"
	python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' \
		"${SANDBOX_METADATA}" "${field_name}"
}

runtime_image_tag() {
	python3 -c '
import json
import os
import sys

metadata = json.load(open(sys.argv[1]))
image_tag = metadata["image_tag"]
sdk_suffix = os.environ.get("YR_K8S_DEFAULT_RUNTIME_SDK_SUFFIX", "cp310")
for image in metadata.get("images", []):
    if "/yr-runtime:" in image:
        print(image.rsplit(":", 1)[1])
        break
else:
    print(f"{image_tag}-{sdk_suffix}")
' "${SANDBOX_METADATA}"
}

configure_image_tags() {
	local base_image_tag
	local pushed_image_tag
	local runtime_arch
	base_image_tag="$(json_field image_tag)"
	pushed_image_tag="$(json_optional_field pushed_image_tag)"

	# Single-architecture releases publish controlplane and node using the
	# architecture suffix recorded in pushed_image_tag. Manifest releases omit
	# that field and publish the arch-less image_tag.
	export YR_K8S_IMAGE_TAG="${YR_K8S_IMAGE_TAG:-${pushed_image_tag:-${base_image_tag}}}"
	export YR_K8S_RUNTIME_IMAGE_TAG="${YR_K8S_RUNTIME_IMAGE_TAG:-$(runtime_image_tag)}"

	# Per-Python runtime images retain their architecture suffix even when the
	# controlplane and node use a multi-architecture manifest tag.
	runtime_arch="${YR_K8S_RUNTIME_IMAGE_ARCH:-amd64}"
	export YR_K8S_RUNTIME_IMAGE_TAG_CP39="${YR_K8S_RUNTIME_IMAGE_TAG_CP39:-${base_image_tag}-${runtime_arch}-cp39}"
	export YR_K8S_RUNTIME_IMAGE_TAG_CP310="${YR_K8S_RUNTIME_IMAGE_TAG_CP310:-${base_image_tag}-${runtime_arch}-cp310}"
	export YR_K8S_RUNTIME_IMAGE_TAG_CP311="${YR_K8S_RUNTIME_IMAGE_TAG_CP311:-${base_image_tag}-${runtime_arch}-cp311}"
	export YR_K8S_RUNTIME_IMAGE_TAG_CP312="${YR_K8S_RUNTIME_IMAGE_TAG_CP312:-${base_image_tag}-${runtime_arch}-cp312}"
	export YR_K8S_RUNTIME_IMAGE_TAG_CP313="${YR_K8S_RUNTIME_IMAGE_TAG_CP313:-${base_image_tag}-${runtime_arch}-cp313}"
	export YR_K8S_RUNTIME_IMAGE_TAG_CP314="${YR_K8S_RUNTIME_IMAGE_TAG_CP314:-${base_image_tag}-${runtime_arch}-cp314}"
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
	*-cp314-*) python_minor="3.14" ;;
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

wait_for_service_address() {
    local service_name="$1"
    local port_name="$2"
	local timeout="${YR_K8S_ADDRESS_TIMEOUT:-300}"
	local deadline=$((SECONDS + timeout))
	local address
	while [ "${SECONDS}" -le "${deadline}" ]; do
        address="$("${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" get svc "${service_name}" -o json |
			PORT_NAME="${port_name}" python3 -c '
import json
import os
import sys

svc = json.load(sys.stdin)
ingress = svc.get("status", {}).get("loadBalancer", {}).get("ingress", [])
hosts = [item.get("ip") or item.get("hostname") for item in ingress]
hosts = [host for host in hosts if host]
public_hosts = [host for host in hosts if not host.startswith(("10.", "172.", "192.168."))]
host = (public_hosts or hosts or [""])[0]
ports = svc.get("spec", {}).get("ports", [])
port = next((item["port"] for item in ports if item.get("name") == os.environ["PORT_NAME"]), "")
if host and port:
    print(f"{host}:{port}")
')" || true
		if [ -n "${address}" ]; then
			printf '%s\n' "${address}"
			return 0
		fi
		sleep 5
	done
    printf 'Timed out waiting for %s/%s LoadBalancer address.\n' "${NAMESPACE}" "${service_name}" >&2
	exit 1
}

cleanup_port_forward() {
    local pid
    for pid in "${PORT_FORWARD_PIDS[@]:-}"; do
        if [ -n "${pid}" ] && kill -0 "${pid}" >/dev/null 2>&1; then
            kill "${pid}" >/dev/null 2>&1 || true
            wait "${pid}" >/dev/null 2>&1 || true
        fi
    done
	PORT_FORWARD_PIDS=()
	USING_LOCAL_PORT_FORWARDS=false
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

start_service_port_forwards() {
    local edge_log="${SMOKE_LOG_DIR}/edge-port-forward.log"
	mkdir -p "${SMOKE_LOG_DIR}"
	if [ "${#PORT_FORWARD_PIDS[@]}" -gt 0 ]; then
		cleanup_port_forward
	fi

    printf 'Starting test-only public Edge service port-forward (no Traefik or Frontend Service)\n' >&2
    "${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" port-forward \
        --address "${PORT_FORWARD_ADDRESS}" "svc/${EDGE_SERVICE}" \
        "${EDGE_TLS_PORT}:8443" "${EDGE_PLAIN_PORT}:8080" >"${edge_log}" 2>&1 &
    PORT_FORWARD_PIDS+=("$!")

    if ! wait_for_local_port "${PORT_FORWARD_ADDRESS}" "${EDGE_TLS_PORT}" \
        "${YR_K8S_PORT_FORWARD_TIMEOUT:-60}"; then
        tail -n 120 "${edge_log}" >&2 || true
        return 1
    fi
    if ! wait_for_local_port "${PORT_FORWARD_ADDRESS}" "${EDGE_PLAIN_PORT}" \
        "${YR_K8S_PORT_FORWARD_TIMEOUT:-60}"; then
        tail -n 120 "${edge_log}" >&2 || true
        return 1
    fi
	USING_LOCAL_PORT_FORWARDS=true
}

service_port_forwards_healthy() {
	local pid
	if [ "${#PORT_FORWARD_PIDS[@]}" -ne 1 ]; then
		return 1
	fi
	for pid in "${PORT_FORWARD_PIDS[@]}"; do
		if ! kill -0 "${pid}" >/dev/null 2>&1; then
			return 1
		fi
	done
	python3 - "${PORT_FORWARD_ADDRESS}" "${EDGE_TLS_PORT}" "${EDGE_PLAIN_PORT}" <<'PY'
import socket
import sys

host = sys.argv[1]
for value in sys.argv[2:]:
    try:
        with socket.create_connection((host, int(value)), timeout=2):
            pass
    except OSError:
        sys.exit(1)
PY
}

ensure_service_port_forwards() {
	if [ "${USING_LOCAL_PORT_FORWARDS}" != true ]; then
		return 0
	fi
	if service_port_forwards_healthy; then
		return 0
	fi
	printf 'Test-only service port-forward stopped; restarting it before the next phase.\n' >&2
	tail -n 80 "${SMOKE_LOG_DIR}/edge-port-forward.log" >&2 || true
	cleanup_port_forward
	start_service_port_forwards
}


dump_k8s_diagnostics() {
	local reason="${1:-unknown}"
	local pod
	if [ ! -f "${KUBECONFIG_PATH}" ] || ! command -v "${KUBECTL_BIN}" >/dev/null 2>&1; then
		return 0
	fi
	printf '\n=== K8S diagnostics (%s) namespace=%s ===\n' "${reason}" "${NAMESPACE}" >&2
	"${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" get pod,svc,deploy,statefulset,daemonset -o wide >&2 || true
	printf '\n--- pod image IDs ---\n' >&2
	"${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" get pods \
		-o jsonpath='{range .items[*]}POD={.metadata.name}{"\n"}{range .spec.containers[*]}  SPEC {.name} image={.image}{"\n"}{end}{range .status.containerStatuses[*]}  STATUS {.name} image={.image} imageID={.imageID}{"\n"}{end}{"\n"}{end}' >&2 || true
	if command -v helm >/dev/null 2>&1; then
		printf '\n--- helm release history ---\n' >&2
		helm -n "${NAMESPACE}" history yr-k8s >&2 || true
		printf '\n--- helm current values ---\n' >&2
		helm -n "${NAMESPACE}" get values yr-k8s -o yaml >&2 || true
	fi
	printf '\n--- recent events ---\n' >&2
	"${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" get events --sort-by=.lastTimestamp 2>/dev/null | tail -80 >&2 || true
	for pod in $("${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" get pods -o name 2>/dev/null | grep -E 'pod/(yr-master|yr-node|yr-frontend)' || true); do
		printf '\n--- logs %s (all containers, tail=200, since=30m) ---\n' "${pod}" >&2
		"${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" logs "${pod}" --all-containers=true --tail=200 --since=30m --prefix >&2 || true
	done
	printf '=== end K8S diagnostics (%s) ===\n\n' "${reason}" >&2
}

on_k8s_test_term() {
	dump_k8s_diagnostics "terminated"
	exit 143
}

wait_for_smoke_ready() {
	local server_address="$1"
	local timeout="${YR_K8S_SMOKE_READY_TIMEOUT:-600}"
	local deadline=$((SECONDS + timeout))
	local attempt=1

	printf 'Waiting for yr-k8s smoke readiness against %s\n' "${server_address}" >&2
	while [ "${SECONDS}" -le "${deadline}" ]; do
		if YR_ENABLE_TLS="${SMOKE_SERVER_TLS}" \
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
		pytest_args=(-m "smoke and not high_reliability_only")
	fi

	printf 'Running yr-k8s off-cluster smoke against %s with %s\n' "${server_address}" "${SMOKE_PYTHON}" >&2
	YR_ENABLE_TLS="${SMOKE_SERVER_TLS}" \
		YR_OFF_CLUSTER_WHEEL_DIR="${RELEASE_ARTIFACT_DIR}" \
		YR_OFF_CLUSTER_USE_UV_VENV=false \
		YR_OFF_CLUSTER_TEST_TIMEOUT="${YR_OFF_CLUSTER_TEST_TIMEOUT:-1200}" \
		UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-300}" \
		YR_LOG_LEVEL="${YR_K8S_SMOKE_LOG_LEVEL:-INFO}" \
		bash test/st/run_off_cluster_test.sh -a "${server_address}" --no-uv-venv -p "${SMOKE_PYTHON}" -- "${pytest_args[@]}" \
		2>&1 | tee "${SMOKE_LOG_DIR}/smoke.log"
}

# Live sandbox-sdk -> Rust data-plane verification: control APIs and /direct
# enter through Edge TLS; /tunnel and standard CONNECT use the configured Edge
# TLS/plain entry. Frontend remains a private Pod-local upstream without a
# Service or test port-forward.
# Edge resolves /yr/route and Node reaches bridge IP without hostPort/DNAT.

extract_sandbox_id() {
	python3 -c '
import base64
import json
import sys


def decode_data(value):
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    padded = value + "=" * (-len(value) % 4)
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            decoded = decoder(padded).decode()
            obj = json.loads(decoded)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return {}

obj = json.load(sys.stdin)
data = decode_data(obj.get("data"))
for key in ("id", "sandboxId", "sandbox_id", "instanceId", "instance_id"):
    value = obj.get(key) or data.get(key)
    if value:
        print(value)
        break
'
}

curl_status() {
	local output="$1"
	shift
	local status
	status="$(curl -sS -o "${output}" -w '%{http_code}' "$@")" || status="000"
	printf '%s\n' "${status}"
}

create_idle_timeout_sandbox() {
	local control_addr="$1"
	local idle_timeout="$2"
	local name="$3"
	local resp_file
	local status
	local sid
	resp_file="$(mktemp)"
	status="$(curl_status "${resp_file}" -k --connect-timeout 10 --max-time 60 \
		-X POST "$(control_origin "${control_addr}")/api/sandbox/v1/sandboxes" \
		-H 'Content-Type: application/json' \
		-d "{\"name\":\"${name}\",\"cpu\":200,\"memory\":256,\"idleTimeoutSeconds\":${idle_timeout}}")"
	if [[ ! "${status}" =~ ^2 ]]; then
		local response_body
		response_body="$(cat "${resp_file}")"
		printf 'idle-timeout: create failed status=%s body=%s\n' "${status}" "${response_body}" >&2
		rm -f "${resp_file}"
		if [[ "${response_body}" == *ERR_RESOURCE_NOT_ENOUGH* ]]; then
			return 75
		fi
		return 1
	fi
	sid="$(extract_sandbox_id <"${resp_file}" 2>/dev/null || true)"
	rm -f "${resp_file}"
	if [ -z "${sid}" ]; then
		printf 'idle-timeout: create returned no sandbox id\n' >&2
		return 1
	fi
	printf '%s\n' "${sid}"
}

create_sandbox_with_capacity_retry() {
	local idle_timeout="$1"
	local name="$2"
	local control_addr="$3"
	local timeout="${YR_K8S_IDLE_CAPACITY_WAIT_TIMEOUT:-180}"
	local deadline=$((SECONDS + timeout))
	local attempt=0
	local sid
	local rc
	while [ "${SECONDS}" -le "${deadline}" ]; do
		attempt=$((attempt + 1))
		# A capacity-rejected create may still reserve the requested instance name
		# in the control plane. Retrying that same name then fails with
		# ERR_INSTANCE_DUPLICATED before capacity can become available, so each
		# bounded capacity attempt must use a distinct identity.
		if sid="$(create_idle_timeout_sandbox "${control_addr}" "${idle_timeout}" "${name}-attempt-${attempt}")"; then
			printf '%s\n' "${sid}"
			return 0
		else
			rc=$?
		fi
		if [ "${rc}" -ne 75 ]; then
			return "${rc}"
		fi
		printf 'idle-timeout: waiting for the previous sandbox capacity to be released\n' >&2
		sleep 5
	done
	printf 'idle-timeout: capacity was not released within %ss\n' "${timeout}" >&2
	return 1
}

invoke_sandbox_status() {
	local control_addr="$1"
	local sid="$2"
	local cmd="$3"
	local output="$4"
	local max_time="${5:-30}"
	curl_status "${output}" -k --connect-timeout 10 --max-time "${max_time}" \
		-X POST "$(control_origin "${control_addr}")/api/sandbox/v1/sandboxes/${sid}/invoke" \
		-H 'Content-Type: application/json' \
		-H "X-Trace-Id: k8s-idle-timeout-${sid}" \
		-d "$(CMD_VALUE="${cmd}" python3 - <<'PYJSON'
import json
import os
print(json.dumps({"action": "process.exec", "args": {"cmd": os.environ["CMD_VALUE"]}}))
PYJSON
		)"
}

control_origin() {
	local address="$1"
	case "${address}" in
	http://* | https://*) printf '%s\n' "${address%/}" ;;
	*)
		if [[ "${SMOKE_SERVER_TLS}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
			printf 'https://%s\n' "${address}"
		else
			printf 'http://%s\n' "${address}"
		fi
		;;
	esac
}

run_idle_timeout_e2e() {
	local control_addr="$1"
	local idle_wait="${YR_K8S_IDLE_TIMEOUT_IDLE_WAIT:-5}"
	local sid
	local status
	local body_file
	local request_id
	local token
	local direct_deadline
	mkdir -p "${SMOKE_LOG_DIR}"
	printf 'Running sandbox idle_timeout e2e against %s (timeout=2s wait=%ss)\n' "$(control_origin "${control_addr}")" "${idle_wait}" >&2

	body_file="${SMOKE_LOG_DIR}/idle_timeout_idle_probe.log"
	sid="$(create_sandbox_with_capacity_retry 2 "idle-timeout-reclaim-${BUILDKITE_BUILD_NUMBER:-local}-${RANDOM}" "${control_addr}")"
	printf '[idle-timeout] created idle reclaim sandbox %s\n' "${sid}" >&2
	sleep "${idle_wait}"
	status="$(invoke_sandbox_status "${control_addr}" "${sid}" 'echo should-not-run-after-idle-timeout' "${body_file}" 10)"
	curl -ksS --connect-timeout 5 --max-time 10 \
		-X DELETE "$(control_origin "${control_addr}")/api/sandbox/v1/sandboxes/${sid}" >/dev/null 2>&1 || true
	if [[ "${status}" =~ ^2 ]]; then
		printf '[idle-timeout] FAIL idle sandbox %s still accepted invoke after %ss. body=%s\n' \
			"${sid}" "${idle_wait}" "$(cat "${body_file}" 2>/dev/null)" >&2
		exit 1
	fi
	printf '[idle-timeout] PASS idle sandbox %s rejected invoke after %ss (status=%s)\n' "${sid}" "${idle_wait}" "${status}" >&2

	# Capacity reuse below is part of the idle assertion: a timeout or route miss
	# alone is not enough to claim reclamation if the instance still owns its
	# scheduler resources.
	body_file="${SMOKE_LOG_DIR}/idle_timeout_busy_probe.log"
	sid="$(create_sandbox_with_capacity_retry 10 "idle-timeout-busy-${BUILDKITE_BUILD_NUMBER:-local}-${RANDOM}" "${control_addr}")"
	printf '[idle-timeout] created busy sandbox %s\n' "${sid}" >&2
	request_id="k8s-idle-busy-${BUILDKITE_BUILD_NUMBER:-local}-${RANDOM}"
	token="$(python3 -c 'import base64,json; b=lambda d: base64.urlsafe_b64encode(json.dumps(d,separators=(",",":")).encode()).rstrip(b"=").decode(); print("{}.{}.sig".format(b({"alg":"none","typ":"JWT"}), b({"sub":"default","role":"developer","exp":4102444800})))')"
	direct_deadline=$((SECONDS + 45))
	while true; do
		status="$(curl_status "${body_file}" -k --connect-timeout 10 --max-time 30 \
			-X POST "$(control_origin "${control_addr}")/direct/${sid}/invoke" \
			-H 'Content-Type: application/json' \
			-H "Authorization: Bearer ${token}" \
			-H "X-Request-Id: ${request_id}" \
			-d "{\"action\":\"process.exec\",\"args\":{\"cmd\":\"sleep 12 && echo busy-alive\"},\"requestId\":\"${request_id}\"}")"
		if [[ "${status}" =~ ^2 ]] || [ "${SECONDS}" -ge "${direct_deadline}" ]; then
			break
		fi
		case "${status}" in
		404 | 409 | 502 | 503 | 504 | 000) sleep 1 ;;
		*) break ;;
		esac
	done
	curl -ksS --connect-timeout 10 --max-time 30 \
		-X DELETE "$(control_origin "${control_addr}")/api/sandbox/v1/sandboxes/${sid}" >/dev/null 2>&1 || true
	if [[ ! "${status}" =~ ^2 ]]; then
		printf '[idle-timeout] FAIL busy sandbox %s was reclaimed or direct invoke failed during 12s request under a 10s idle timeout (status=%s). body=%s\n' \
			"${sid}" "${status}" "$(cat "${body_file}" 2>/dev/null)" >&2
		exit 1
	fi
	printf '[idle-timeout] PASS busy sandbox %s survived a 12s direct data-plane request under a 10s idle timeout\n' "${sid}" >&2
}

run_rrt_direct_e2e() {
	local frontend_addr="$1"
	local router_tls_addr="$2"
	local router_plain_addr="$3"
	local wheel
	local py
	mkdir -p "${SMOKE_LOG_DIR}"
	git submodule update --init --recursive sandbox-sdk >&2 || true
	# sandbox-sdk requires Python >=3.10; the image's default python3 is 3.9.
	# Reuse the smoke interpreter (cp311) or fall back to any >=3.10 build python,
	# and hand it to build.sh (which honors $PYTHON) so the wheel build/install
	# don't 'requires a different Python' on 3.9.
	py="${SMOKE_PYTHON:-$(command -v python3.11 || command -v python3.12 || command -v python3.10 || command -v python3.13 || command -v python3)}"
	# build.sh falls back to `pip wheel`, whose PEP 517 build-isolation subprocess
	# fetches the build deps (setuptools-scm>=8) from a package index. The cluster
	# agents have no usable default index, so point the inherited PIP_* env at the
	# HuaweiCloud mirror (same as the Build SDK step). Without this the isolated
	# build fails with "No matching distribution found for setuptools-scm>=8".
	export PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.huaweicloud.com/repository/pypi/simple}"
	export PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-mirrors.huaweicloud.com}"
	PYTHON="${py}" bash sandbox-sdk/build.sh "${RELEASE_ARTIFACT_DIR}" >&2
	wheel="$(find "${RELEASE_ARTIFACT_DIR}" -maxdepth 1 -type f -name 'openyuanrong_sandbox-*.whl' | sort -V | tail -1)"
	if [ -z "${wheel}" ]; then
		printf 'sandbox-sdk wheel not built under %s\n' "${RELEASE_ARTIFACT_DIR}" >&2
		exit 1
	fi
	PIP_BREAK_SYSTEM_PACKAGES=1 "${py}" -m pip install --force-reinstall \
		--index-url "${YR_K8S_SMOKE_PIP_INDEX_URL:-https://repo.huaweicloud.com/repository/pypi/simple}" \
		--trusted-host "${YR_K8S_SMOKE_PIP_TRUSTED_HOST:-repo.huaweicloud.com}" \
		"${wheel}"
	# Keep one structurally valid token for control-plane lifecycle calls and SDK
	# request construction. The isolated smoke overlay disables IAM validation at
	# Edge; production Edge requires Authorization bearer validation and may call
	# IAM. An externally supplied real YR_TOKEN still takes precedence.
	local yr_token="${YR_TOKEN:-}"
	if [ -z "${yr_token}" ]; then
		yr_token="$("${py}" -c 'import base64,json; b=lambda d: base64.urlsafe_b64encode(json.dumps(d,separators=(",",":")).encode()).rstrip(b"=").decode(); print("{}.{}.sig".format(b({"alg":"none","typ":"JWT"}), b({"sub":"default","role":"developer","exp":4102444800})))')"
	fi
	printf 'Running sandbox-sdk -> Rust Edge direct e2e (frontend=%s edge=%s path=/direct)\n' \
		"${frontend_addr}" "${router_tls_addr}" >&2
	YR_SERVER_ADDRESS="${frontend_addr}" \
		YR_GATEWAY_ADDRESS="${router_tls_addr}" \
		YR_TLS="${SMOKE_SERVER_TLS}" \
		YR_GATEWAY_TLS=1 \
		YR_TOKEN="${yr_token}" \
		"${py}" sandbox-sdk/python/tests/e2e_rrt_direct.py \
		2>&1 | tee "${SMOKE_LOG_DIR}/rrt_direct.log"

	# SDK example smoke against the live cluster. CORE examples gate the build.
	# Keep reverse_tunnel as best-effort because it depends on a local CI HTTP
	# server plus a long-lived WS tunnel and is flaky in the shared Buildkite
	# network; tunnel_large_response remains a core tunnel data-plane gate.
	if [[ "${YR_K8S_RUN_EXAMPLES:-true}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
		local core_examples="basic_usage command_stdin persistent_shell tunnel_large_response port_forwarding"
		local extra_examples="reverse_tunnel named_sandbox bench_cp"
		local ex rc core_fail=0
		local attempt deadline example_log
		local capacity_wait_timeout="${YR_K8S_EXAMPLE_CAPACITY_WAIT_TIMEOUT:-180}"
		printf '[examples] env YR_SERVER_ADDRESS=%s YR_GATEWAY_ADDRESS=%s YR_TLS=%s YR_GATEWAY_TLS=0 TUNNEL_SSL_VERIFY=0\n' "${frontend_addr}" "${router_plain_addr}" "${SMOKE_SERVER_TLS}" >&2
		for ex in ${core_examples} ${extra_examples}; do
			local f="sandbox-sdk/python/examples/${ex}.py"
			[ -f "${f}" ] || {
				printf '[examples] SKIP %s (missing)\n' "${ex}" >&2
				continue
			}
			printf '[examples] RUN %s\n' "${ex}" >&2
			printf '[examples] ---- %s log ----\n' "${ex}" >&2
			example_log="${SMOKE_LOG_DIR}/example_${ex}.log"
			: >"${example_log}"
			attempt=0
			deadline=$((SECONDS + capacity_wait_timeout))
			while true; do
				attempt=$((attempt + 1))
				printf '[examples] attempt %s for %s\n' "${attempt}" "${ex}" >&2
				if YR_SERVER_ADDRESS="${frontend_addr}" YR_GATEWAY_ADDRESS="${router_plain_addr}" YR_TLS="${SMOKE_SERVER_TLS}" YR_GATEWAY_TLS=0 YR_EXAMPLE_CPU=2000 YR_EXAMPLE_MEMORY=4096 YR_TOKEN="${yr_token}" TUNNEL_SSL_VERIFY=0 timeout 180 "${py}" "${f}" 2>&1 | tee "${example_log}"; then
					printf '[examples] PASS %s\n' "${ex}" >&2
					rc=0
					break
				else
					rc=$?
				fi
				# Deletion and scheduler resource release are asynchronous in the
				# shared smoke cluster. Retry only a create-time capacity rejection;
				# protocol, assertion and data-plane failures remain immediate.
				if [ "${SECONDS}" -lt "${deadline}" ] &&
					grep -Fq 'sandbox create failed' "${example_log}" &&
					grep -Eq 'ERR_RESOURCE_NOT_ENOUGH|No Resource In Cluster|Out Of Capacity' "${example_log}"; then
					printf '[examples] capacity unavailable for %s; retrying after 5s\n' "${ex}" >&2
					sleep 5
					continue
				fi
				# Example stdout/stderr is streamed inline for both pass and fail so
				# CI keeps the runnable demonstration output instead of silently
				# passing. Classification only decides whether a failure gates.
				case " ${core_examples} " in
				*" ${ex} "*)
					printf '[examples] FAIL %s (core, rc=%s)\n' "${ex}" "${rc}" >&2
					core_fail=1
					;;
				*) printf '[examples] WARN %s (best-effort, rc=%s)\n' "${ex}" "${rc}" >&2 ;;
				esac
				break
			done
			printf '[examples] ---- end %s log ----\n' "${ex}" >&2
		done
		if [ "${core_fail}" = "1" ]; then
			printf 'core SDK examples failed; see %s/example_*.log\n' "${SMOKE_LOG_DIR}" >&2
			exit 1
		fi
	fi
}

verify_rust_data_plane_ready() {
	local frontend_pod node_pod
	frontend_pod="$("${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" get pod \
		-l app.kubernetes.io/instance="${RELEASE_NAME}",app.kubernetes.io/component=frontend \
		-o jsonpath='{.items[0].metadata.name}')"
	node_pod="$("${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" get pod \
		-l app.kubernetes.io/instance="${RELEASE_NAME}",app.kubernetes.io/component=node \
		-o jsonpath='{.items[0].metadata.name}')"
	[ -n "${frontend_pod}" ] && [ -n "${node_pod}" ] || {
		printf 'Rust data plane pods are missing (frontend=%s node=%s).\n' "${frontend_pod}" "${node_pod}" >&2
		return 1
	}
	printf 'Verifying Rust Edge in pod/%s and Rust Node Proxy in pod/%s\n' "${frontend_pod}" "${node_pod}" >&2
	"${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" exec "${frontend_pod}" \
		-c edge-frontend -- python3 -c \
		'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:18080/readyz", timeout=5).read().decode())'
	"${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" exec "${node_pod}" \
		-c node -- python3 -c \
		'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:18443/readyz", timeout=5).read().decode())'
}

prepare_edge_tls_secret() {
	local secret_name="${YR_K8S_EDGE_TLS_SECRET:-yr-edge-frontend-tls}"
	local tls_dir
	require_bin openssl
	mkdir -p "$(dirname "${EDGE_TLS_CA_FILE}")"
	tls_dir="$(mktemp -d)"
	openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
		-subj /CN=127.0.0.1 \
		-addext "subjectAltName=IP:127.0.0.1,DNS:${EDGE_SERVICE},DNS:${EDGE_SERVICE}.${NAMESPACE}.svc" \
		-keyout "${tls_dir}/tls.key" -out "${tls_dir}/tls.crt" >/dev/null 2>&1
	install -m 0644 "${tls_dir}/tls.crt" "${EDGE_TLS_CA_FILE}"
	"${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" create namespace "${NAMESPACE}" \
		--dry-run=client -o yaml | \
		"${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" apply -f - >/dev/null
	"${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" \
		create secret tls "${secret_name}" --cert "${tls_dir}/tls.crt" \
		--key "${tls_dir}/tls.key" --dry-run=client -o yaml | \
		"${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" apply -f - >/dev/null
	rm -rf "${tls_dir}"
}

main() {
	local smoke_server_address
	local router_tls_address
	local router_plain_address
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
	configure_image_tags
	export YR_K8S_REGISTRY_REPO="${YR_K8S_REGISTRY_REPO:-$(json_field registry)}"
	export HELM_BIN

	# Control-port auth (enableJwt) stays ON so the test exercises control-port
	# gating, but turn validateIam OFF for this CI deploy: there is no real IAM
	# token in CI, so the router accepts the structurally-valid unsigned JWT minted
	# in run_rrt_direct_e2e. Production keeps validateIam=true (chart default).
	export YR_K8S_VALIDATE_IAM="${YR_K8S_VALIDATE_IAM:-false}"
	# K8S smoke uses the cp311 SDK/runtime. The all-version SDK/runtime build
	# matrix is validated by dedicated Buildkite steps; pre-pulling every runtime
	# image on every test node can exhaust the CI pod before tests start.
	export YR_K8S_PREPULL_RUNTIME_SUFFIXES="${YR_K8S_PREPULL_RUNTIME_SUFFIXES:-cp311}"
	export YR_K8S_EXTRA_VALUES_FILE="${YR_K8S_EXTRA_VALUES_FILE:-${ROOT_DIR}/deploy/sandbox/k8s/k8s/values.buildkite-smoke.yaml}"
	trap cleanup_port_forward EXIT

	prepare_edge_tls_secret
	bash deploy/sandbox/k8s/deploy.sh
	trap 'dump_k8s_diagnostics "error"' ERR
	trap on_k8s_test_term TERM INT
	verify_rust_data_plane_ready
	# The K8S smoke generates a short-lived self-signed Edge certificate above.
	# Keep verification enabled and teach every SDK subprocess to trust that
	# exact certificate instead of disabling TLS verification for CI.
	export YR_VERIFY_FILE="${YR_VERIFY_FILE:-${EDGE_TLS_CA_FILE}}"
	printf 'Kubernetes node capacity used by the sandbox smoke cluster:\n' >&2
	"${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" get nodes \
		-o 'custom-columns=NAME:.metadata.name,CPU_CAPACITY:.status.capacity.cpu,CPU_ALLOCATABLE:.status.allocatable.cpu,MEMORY_ALLOCATABLE:.status.allocatable.memory' >&2 || true
	"${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" get pods \
		-l app.kubernetes.io/instance="${RELEASE_NAME}",app.kubernetes.io/component=node \
		-o 'custom-columns=POD:.metadata.name,K8S_NODE:.spec.nodeName,POD_IP:.status.podIP,READY:.status.containerStatuses[*].ready' >&2 || true
	smoke_server_address="${YR_K8S_SMOKE_SERVER_ADDRESS:-}"
	router_tls_address="${YR_K8S_ROUTER_TLS_ADDRESS:-}"
	router_plain_address="${YR_K8S_ROUTER_PLAIN_ADDRESS:-}"
	if [ -z "${router_tls_address}" ] || [ -z "${router_plain_address}" ]; then
		start_service_port_forwards
		router_tls_address="${router_tls_address:-${EDGE_TLS_ADDRESS}}"
		router_plain_address="${router_plain_address:-${EDGE_PLAIN_ADDRESS}}"
	fi
	# Edge owns the external TLS control entry and statically forwards lifecycle
	# requests to the private Frontend process. Exercise that real deployment
	# path instead of adding a test-only Frontend Service/port-forward.
	smoke_server_address="${smoke_server_address:-${router_tls_address}}"

	# Smoke-probe: actually create a sandbox using the frontend's default
	# isolation runtime to verify the full create path before running tests.
	# deploy.sh only waits for the control-plane workloads (frontend/etcd/master)
	# to roll out. It cannot detect API contract regressions or runtime capacity
	# failures. A failed probe must fail the job because no smoke coverage ran.
	probe_sandbox_ready() {
		local endpoint="$1"
		local base_url="${endpoint}"
		local resp
		local sid
		[[ "${base_url}" == *://* ]] || base_url="http://${base_url}"
		resp="$(curl -ksS --connect-timeout 10 --max-time 60 \
			-X POST "${base_url}/api/sandbox/v1/sandboxes" \
			-H 'Content-Type: application/json' \
			-d '{"cpu":200,"memory":256,"idleTimeoutSeconds":30}')" || {
			printf 'Cluster sandbox probe: CREATE request failed (endpoint=%s).\n' "${base_url}" >&2
			printf 'Smoke precondition failed; no tests were run.\n' >&2
			return 1
		}
		sid="$(printf '%s' "${resp}" | extract_sandbox_id 2>/dev/null)" || true
		if [ -z "${sid}" ]; then
			printf 'Cluster sandbox probe: CREATE returned no sandbox ID.\n' >&2
			printf 'Response body: %s\n' "${resp}" >&2
			printf 'Smoke precondition failed; no tests were run.\n' >&2
			return 1
		fi
		printf 'Cluster sandbox probe: created %s, cleaning up.\n' "${sid}" >&2
		curl -ksS --connect-timeout 10 --max-time 30 \
			-X DELETE "${base_url}/api/sandbox/v1/sandboxes/${sid}" >/dev/null 2>&1 || true
		return 0
	}
	# Prove the public Edge TLS listener owns the control-plane static route;
	# the legacy Frontend Service is intentionally absent in this deployment.
	if ! probe_sandbox_ready "https://${router_tls_address}"; then
		if command -v buildkite-agent >/dev/null 2>&1; then
			buildkite-agent annotate --style "error" --context "sandbox-k8s-probe-failed" \
				"Cluster sandbox probe failed. No smoke or example tests were run; inspect the CREATE response above."
		fi
		exit 1
	fi

	if [[ "${YR_K8S_RUN_IDLE_TIMEOUT:-true}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
		ensure_service_port_forwards
		run_idle_timeout_e2e "${smoke_server_address}"
	fi

	if [[ "${YR_K8S_RUN_SMOKE:-true}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
		ensure_service_port_forwards
		run_smoke "${smoke_server_address}"
	fi

	if [[ "${YR_K8S_RUN_RRT_DIRECT:-true}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
		ensure_service_port_forwards
		run_rrt_direct_e2e "${smoke_server_address}" "${router_tls_address}" "${router_plain_address}"
	fi

	if command -v buildkite-agent >/dev/null 2>&1; then
		buildkite-agent annotate --style "success" --context "sandbox-k8s" \
			"Deployed sandbox image tag ${YR_K8S_IMAGE_TAG} with Rust Edge/Node data plane and passed idle-timeout + SDK direct/copy/tunnel/port-forward checks."
	fi
}

main "$@"
