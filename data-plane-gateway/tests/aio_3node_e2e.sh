#!/usr/bin/env bash
# Real 3-node AIO validation for:
# FunctionSystem -> runtime-launcher -> bridge endpoint -> /yr/route ->
# Edge Frontend -> H2 CONNECT -> owning Node Proxy -> sandbox TCP port.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ASSETS="$ROOT/data-plane-gateway/tests/aio_3node"
BASE_IMAGE="${YR_GATEWAY_AIO_BASE:-yr-local-aio:latest}"
TEST_IMAGE="${YR_GATEWAY_AIO_IMAGE:-yr-data-plane-gateway-aio:e2e}"
SANDBOX_RUNTIME_IMAGE="${YR_GATEWAY_AIO_RUNTIME_IMAGE:-aio-yr-runtime:latest}"
SDK_RUNTIME_IMAGE="${YR_GATEWAY_SDK_RUNTIME_IMAGE:-yr-gateway-sdk-runtime:e2e}"
SDK_DRIVER_IMAGE="${YR_GATEWAY_SDK_DRIVER_IMAGE:-yr-gateway-sdk-driver:e2e}"
BUILDER_IMAGE="${YR_GATEWAY_RUST_BUILDER:-yr-data-plane-gateway-rust-builder:1.88-arm64}"
FRONTEND_BUILDER_IMAGE="${YR_GATEWAY_FRONTEND_BUILDER:-yr-data-plane-gateway-frontend-builder:1.24.1-arm64}"
RRT_BUILDER_IMAGE="${YR_GATEWAY_RRT_BUILDER:-openyuanrong/rrt-rust-dev:1.85.1-arm64}"
NETWORK="${YR_GATEWAY_AIO_NETWORK:-yr-gateway-e2e-net}"
MASTER="${YR_GATEWAY_AIO_MASTER:-yr-gateway-e2e-master}"
WORKER2="${YR_GATEWAY_AIO_WORKER2:-yr-gateway-e2e-worker2}"
WORKER3="${YR_GATEWAY_AIO_WORKER3:-yr-gateway-e2e-worker3}"
EDGE="${YR_GATEWAY_AIO_EDGE:-yr-gateway-e2e-edge}"
SDK_DRIVER="${YR_GATEWAY_AIO_SDK_DRIVER:-yr-gateway-e2e-sdk-driver}"
RESULT_ROOT="${YR_GATEWAY_AIO_RESULTS:-$ROOT/.yr-cache/data-plane-gateway-aio}"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
RESULT_DIR="$RESULT_ROOT/$RUN_ID"
LINUX_OUT="$ROOT/data-plane-gateway/target/linux-aarch64-release"
MASTER_INFO_CURRENT=/tmp/yr_sessions/yr_current_master_info
MASTER_INFO_LEGACY=/tmp/yr_sessions/latest/master.info

log() { printf '[gateway-aio] %s\n' "$*"; }
die() { printf '[gateway-aio] ERROR: %s\n' "$*" >&2; exit 1; }

container_ip() {
    docker inspect "$1" --format "{{with index .NetworkSettings.Networks \"$NETWORK\"}}{{.IPAddress}}{{end}}"
}

master_info() {
    docker exec "$MASTER" bash -lc "if [ -s '$MASTER_INFO_CURRENT' ]; then cat '$MASTER_INFO_CURRENT'; else cat '$MASTER_INFO_LEGACY'; fi"
}

info_field() {
    printf '%s\n' "$1" | tr ',' '\n' | awk -F: -v key="$2" '$1 == key {print $2; exit}'
}

cleanup() {
    local status=$?
    mkdir -p "$RESULT_DIR"
    if docker inspect "$SDK_DRIVER" >/dev/null 2>&1; then
        docker logs "$SDK_DRIVER" >"$RESULT_DIR/$SDK_DRIVER.log" 2>&1 || true
    fi
    for container in "$MASTER" "$WORKER2" "$WORKER3" "$EDGE"; do
        if docker inspect "$container" >/dev/null 2>&1; then
            docker logs "$container" >"$RESULT_DIR/$container.log" 2>&1 || true
            docker exec "$container" bash -lc 'find /tmp/yr_sessions -maxdepth 3 -type f -print -exec sed -n "1,220p" {} \;' \
                >"$RESULT_DIR/$container.sessions.txt" 2>&1 || true
            local session_root
            session_root="$(docker exec "$container" readlink -f /tmp/yr_sessions/latest 2>/dev/null || true)"
            if [ -n "$session_root" ]; then
                mkdir -p "$RESULT_DIR/$container-function-system"
                docker cp "$container:$session_root/logs/function_system/." \
                    "$RESULT_DIR/$container-function-system/" >/dev/null 2>&1 || true
            fi
            docker cp "$container:/var/log/supervisor/runtime-launcher.log" \
                "$RESULT_DIR/$container-runtime-launcher.log" >/dev/null 2>&1 || true
        fi
    done
    if [ "${YR_GATEWAY_AIO_KEEP:-0}" != 1 ]; then
        docker rm -f "$SDK_DRIVER" "$EDGE" "$WORKER3" "$WORKER2" "$MASTER" >/dev/null 2>&1 || true
        docker network rm "$NETWORK" >/dev/null 2>&1 || true
    else
        log "keeping containers and network because YR_GATEWAY_AIO_KEEP=1"
    fi
    if [ "$status" -ne 0 ]; then
        log "FAILED; diagnostics: $RESULT_DIR"
    fi
    exit "$status"
}

wait_http() {
    local container=$1 url=$2 description=$3 i code
    for i in $(seq 1 90); do
        code="$(docker exec "$container" curl -sS -m 3 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
        if [ "$code" = 200 ]; then
            log "$description ready after about $((i * 3))s"
            return 0
        fi
        sleep 3
    done
    die "$description did not become ready (last HTTP code: ${code:-none})"
}

assert_no_traefik() {
    local container=$1 status
    status="$(docker exec "$container" supervisorctl status 2>&1 || true)"
    if printf '%s\n' "$status" | grep -qi traefik; then
        die "Traefik unexpectedly running in $container: $status"
    fi
    log "$container has no Traefik process"
}

wait_nodes() {
    local master_ip=$1 scheduler_port=$2 i count
    for i in $(seq 1 100); do
        count="$(docker exec "$MASTER" curl -fsS -m 4 "http://$master_ip:$scheduler_port/global-scheduler/resources" 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); f=d.get("resource",{}).get("fragment",{}); print(len(f) if isinstance(f,dict) else d.get("node_count",0))' 2>/dev/null || true)"
        if [ "$count" = 3 ]; then
            log "all 3 AIO nodes registered"
            return 0
        fi
        sleep 3
    done
    die "only ${count:-0}/3 nodes registered"
}

load_sandbox_runtime_image() {
    [ "$SANDBOX_RUNTIME_IMAGE" = "aio-yr-runtime:latest" ] || \
        die "sandbox_runtime.json currently requires aio-yr-runtime:latest"
    docker image inspect "$SANDBOX_RUNTIME_IMAGE" >/dev/null 2>&1 || \
        die "sandbox runtime image not found: $SANDBOX_RUNTIME_IMAGE"
    for container in "$MASTER" "$WORKER2" "$WORKER3"; do
        log "loading $SANDBOX_RUNTIME_IMAGE into $container nested Docker"
        docker save "$SANDBOX_RUNTIME_IMAGE" | docker exec -i "$container" docker load >/dev/null
        docker exec "$container" docker image inspect "$SANDBOX_RUNTIME_IMAGE" >/dev/null
    done
}

load_sdk_runtime_image() {
    docker image inspect "$SDK_RUNTIME_IMAGE" >/dev/null 2>&1 || \
        die "SDK runtime image not found: $SDK_RUNTIME_IMAGE"
    for container in "$MASTER" "$WORKER2" "$WORKER3"; do
        log "loading $SDK_RUNTIME_IMAGE into $container nested Docker"
        docker save "$SDK_RUNTIME_IMAGE" | docker exec -i "$container" docker load >/dev/null
        docker exec "$container" docker image inspect "$SDK_RUNTIME_IMAGE" >/dev/null
    done
}

build_gateway() {
    docker image inspect rust:1.88-bookworm >/dev/null 2>&1 || die "local rust:1.88-bookworm image is required"
    log "checking reusable Rust 1.88 Linux arm64 builder"
    docker build --network host -t "$BUILDER_IMAGE" -f "$ASSETS/Dockerfile.rust-builder" "$ROOT"
    mkdir -p "$LINUX_OUT"
    log "building Linux arm64 Gateway binaries with locked dependencies"
    docker run --rm \
        -v "$ROOT/data-plane-gateway:/workspace" \
        -v yr-cargo-home:/cargo \
        -v yr-yuanrong-release-cargo-target:/target \
        -e CARGO_HOME=/cargo \
        -e CARGO_TARGET_DIR=/target/linux-aarch64-rust1.88.0 \
        -e CC=musl-gcc \
        -e CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER=musl-gcc \
        -e 'RUSTFLAGS=-C target-feature=+crt-static -C link-self-contained=yes -C relocation-model=static' \
        -w /workspace \
        "$BUILDER_IMAGE" \
        cargo build --locked --release --all-features --bins --target aarch64-unknown-linux-musl
    local staging="yr-gateway-linux-copy-$RUN_ID"
    docker create --name "$staging" \
        -v yr-yuanrong-release-cargo-target:/target \
        "$BUILDER_IMAGE" true >/dev/null
    for binary in yr-node-proxy yr-edge-frontend yr-data-plane-forward; do
        docker run --rm \
            -v yr-yuanrong-release-cargo-target:/target \
            "$BUILDER_IMAGE" \
            strip "/target/linux-aarch64-rust1.88.0/aarch64-unknown-linux-musl/release/$binary"
        docker cp "$staging:/target/linux-aarch64-rust1.88.0/aarch64-unknown-linux-musl/release/$binary" "$LINUX_OUT/$binary"
    done
    docker rm "$staging" >/dev/null
    "$ROOT/data-plane-gateway/scripts/verify-static-linux.sh" \
        "$LINUX_OUT/yr-node-proxy" \
        "$LINUX_OUT/yr-edge-frontend" \
        "$LINUX_OUT/yr-data-plane-forward"
    file "$LINUX_OUT/yr-node-proxy" | grep -q 'ELF 64-bit.*ARM aarch64' || die "yr-node-proxy is not Linux arm64"
    log "static Linux binaries staged in $LINUX_OUT"
}

build_frontend() {
    log "building the current Linux arm64 Frontend plugin for direct control-plane access"
    docker build --network host \
        -t "$FRONTEND_BUILDER_IMAGE" \
        -f "$ASSETS/Dockerfile.frontend-builder" \
        "$ROOT"
    mkdir -p "$LINUX_OUT"
    docker run --rm \
        -v "$ROOT:/workspace" \
        -v yr-data-plane-gateway-go-cache:/go \
        "$FRONTEND_BUILDER_IMAGE" sh -c '
          set -eu
          mkdir -p /tmp/source/api
          cp -a /workspace/frontend /tmp/source/frontend
          cp -a /workspace/api/go /tmp/source/api/go
          mkdir -p /tmp/source/build/output/runtime/service/go
          cp -a /opt/aio-go-bin /tmp/source/build/output/runtime/service/go/bin
          cd /tmp/source/api/go
          LD_LIBRARY_PATH=/tmp/source/build/output/runtime/service/go/bin \
            go build -buildmode=pie \
              -o /workspace/data-plane-gateway/target/linux-aarch64-release/goruntime \
              ./runtime/yr_runtime_main.go
          cd /tmp/source/frontend
          go mod tidy
          bash build/gen_grpc_pb.sh
          go build -tags function -buildmode=plugin \
            -o /workspace/data-plane-gateway/target/linux-aarch64-release/faasfrontend.so \
            ./cmd/faasfrontend/function_main.go
        '
    file "$LINUX_OUT/faasfrontend.so" | grep -q 'ELF 64-bit.*ARM aarch64' || \
        die "faasfrontend.so is not Linux arm64"
    file "$LINUX_OUT/goruntime" | grep -q 'ELF 64-bit.*ARM aarch64' || \
        die "goruntime is not Linux arm64"
}

build_rrt_runtime() {
    mkdir -p "$LINUX_OUT"
    docker image inspect "$RRT_BUILDER_IMAGE" >/dev/null 2>&1 || \
        die "local RRT builder image is required: $RRT_BUILDER_IMAGE"
    docker volume inspect yr-cargo-home yr-yuanrong-release-cargo-target >/dev/null 2>&1 || \
        die "prewarmed yr-cargo-home and yr-yuanrong-release-cargo-target volumes are required"
    log "building Linux arm64 rrt-runtime with the prewarmed release cache"
    docker run --rm --network host \
        -v "$ROOT/api/rust:/ws" \
        -v yr-cargo-home:/cargo \
        -v yr-yuanrong-release-cargo-target:/target \
        -e CARGO_HOME=/cargo \
        -e CARGO_TARGET_DIR=/target/linux-aarch64-rust1.85.1 \
        -w /ws \
        "$RRT_BUILDER_IMAGE" \
        cargo build --locked --release -p rrt-daemon --bin rrt-runtime
    local staging="yr-rrt-linux-copy-$RUN_ID"
    docker create --name "$staging" \
        -v yr-yuanrong-release-cargo-target:/target \
        "$RRT_BUILDER_IMAGE" true >/dev/null
    docker cp "$staging:/target/linux-aarch64-rust1.85.1/release/rrt-runtime" "$LINUX_OUT/rrt-runtime"
    docker rm "$staging" >/dev/null
    file "$LINUX_OUT/rrt-runtime" | grep -q 'ELF 64-bit.*ARM aarch64' || \
        die "rrt-runtime is not Linux arm64"
}

build_image() {
    docker image inspect "$BASE_IMAGE" >/dev/null 2>&1 || die "AIO base image not found: $BASE_IMAGE"
    [ -x "$ROOT/functionsystem/functionsystem/build/bin/function_proxy" ] || die "build current Linux function_proxy first"
    [ -x "$ROOT/functionsystem/runtime-launcher/bin/runtime/runtime-launcher" ] || die "build current Linux runtime-launcher first"
    [ -x "$LINUX_OUT/rrt-runtime" ] || build_rrt_runtime
    [ -x "$LINUX_OUT/yr-node-proxy" ] || build_gateway
    [ -f "$LINUX_OUT/faasfrontend.so" ] || build_frontend
    log "building AIO overlay $TEST_IMAGE from $BASE_IMAGE"
    docker build \
        --build-arg "BASE_IMAGE=$BASE_IMAGE" \
        -t "$TEST_IMAGE" \
        -f "$ASSETS/Dockerfile" \
        "$ROOT"
    docker run --rm --entrypoint bash "$TEST_IMAGE" -lc '
        set -e
        YR_ROOT=$(python3 -c "from pathlib import Path; import yr; print(Path(yr.__file__).resolve().parent)")
        test -x "$YR_ROOT/functionsystem/bin/function_proxy"
        test -x /openyuanrong/runtime-launcher
        test -x "$YR_ROOT/data_plane/bin/yr-node-proxy"
        ldd "$YR_ROOT/functionsystem/bin/function_proxy" >/dev/null
        /usr/local/bin/yr start --help | grep -q -- --edge
    '
}

build_sdk_images() {
    log "building SDK sandbox runtime $SDK_RUNTIME_IMAGE"
    docker build \
        --build-arg "BASE_IMAGE=$SANDBOX_RUNTIME_IMAGE" \
        -t "$SDK_RUNTIME_IMAGE" \
        -f "$ASSETS/Dockerfile.sdk-runtime" \
        "$ROOT"
    docker run --rm --entrypoint sh "$SDK_RUNTIME_IMAGE" -lc '
        test -x /usr/local/bin/rrt-runtime
        ldd /usr/local/bin/rrt-runtime >/dev/null
    '
    log "building Python 3.12 sandbox-sdk driver $SDK_DRIVER_IMAGE"
    docker build --network host \
        -t "$SDK_DRIVER_IMAGE" \
        -f "$ASSETS/Dockerfile.sdk-driver" \
        "$ROOT"
}

write_worker_start() {
    local container=$1 master_ip=$2 scheduler_port=$3 ds_master_port=$4 node_tag=$5
    local rendered="$RESULT_DIR/$container-start.sh"
    sed \
        -e "s|__MASTER_IP__|$master_ip|g" \
        -e "s|__GLOBAL_SCHEDULER_PORT__|$scheduler_port|g" \
        -e "s|__DS_MASTER_PORT__|$ds_master_port|g" \
        -e "s|__NODE_TAG__|$node_tag|g" \
        "$ASSETS/start-worker.sh" >"$rendered"
    chmod 0755 "$rendered"
    docker cp "$rendered" "$container:/usr/local/bin/start-yuanrong.sh"
}

start_cluster() {
    mkdir -p "$RESULT_DIR"
    docker rm -f "$EDGE" "$WORKER3" "$WORKER2" "$MASTER" >/dev/null 2>&1 || true
    docker network rm "$NETWORK" >/dev/null 2>&1 || true
    docker network create --subnet 10.250.0.0/24 "$NETWORK" >/dev/null

    log "starting AIO master"
    docker run -d --name "$MASTER" --hostname gateway-master \
        --network "$NETWORK" --ip 10.250.0.10 \
        --privileged --cgroupns host \
        -v "$ASSETS/start-master.sh:/usr/local/bin/start-yuanrong.sh:ro" \
        "$TEST_IMAGE" >/dev/null
    wait_http "$MASTER" http://10.250.0.10:8889/ "master Frontend"
    wait_http "$MASTER" http://127.0.0.1:18443/readyz "master Node Proxy"
    assert_no_traefik "$MASTER"

    local info master_ip scheduler_port ds_master_port
    info="$(master_info)"
    master_ip="$(info_field "$info" master_ip)"
    scheduler_port="$(info_field "$info" global_scheduler_port)"
    ds_master_port="$(info_field "$info" ds_master_port)"
    [ -n "$master_ip" ] || master_ip="$(container_ip "$MASTER")"
    [ -n "$scheduler_port" ] || die "global_scheduler_port missing from master info: $info"
    [ -n "$ds_master_port" ] || die "ds_master_port missing from master info: $info"

    for spec in "$WORKER2:10.250.0.12:node_tag2" "$WORKER3:10.250.0.13:node_tag3"; do
        IFS=: read -r container ip tag <<<"$spec"
        docker create --name "$container" --hostname "$tag" \
            --network "$NETWORK" --ip "$ip" \
            --privileged --cgroupns host "$TEST_IMAGE" >/dev/null
        write_worker_start "$container" "$master_ip" "$scheduler_port" "$ds_master_port" "$tag"
        docker start "$container" >/dev/null
        log "started $container ($tag)"
    done
    wait_nodes "$master_ip" "$scheduler_port"
    wait_http "$WORKER2" http://127.0.0.1:18443/readyz "worker2 Node Proxy"
    wait_http "$WORKER3" http://127.0.0.1:18443/readyz "worker3 Node Proxy"
    assert_no_traefik "$WORKER2"
    assert_no_traefik "$WORKER3"
    load_sandbox_runtime_image

    local etcd_port
    etcd_port="$(info_field "$info" etcd_port)"
    [ -n "$etcd_port" ] || die "etcd_port missing from master info: $info"
    docker run -d --name "$EDGE" --hostname edge-frontend \
        --network "$NETWORK" --ip 10.250.0.20 \
        --entrypoint /usr/local/lib/yr-gateway-e2e/start-edge.sh \
        -e "YR_GATEWAY_E2E_ETCD=http://$master_ip:$etcd_port" \
        "$TEST_IMAGE" >/dev/null
    wait_http "$EDGE" http://127.0.0.1:18080/readyz "Edge Frontend"
    printf '%s\n' "$info" >"$RESULT_DIR/master.info"
}

prepare_driver() {
    local info=$1 master_ip proxy_grpc ds_port
    master_ip="$(info_field "$info" master_ip)"
    proxy_grpc="$(info_field "$info" bus)"
    ds_port="$(info_field "$info" ds-worker)"
    [ -n "$proxy_grpc" ] || proxy_grpc=22773
    [ -n "$ds_port" ] || ds_port=31501
    docker exec "$MASTER" bash -lc "mkdir -p /root/.yr /home/sn/.yr"
    docker exec -i "$MASTER" bash -lc 'tee /root/.yr/config.ini >/dev/null; cp /root/.yr/config.ini /home/sn/.yr/config.ini' <<EOF
[python]
server_address=$master_ip:$proxy_grpc
datasystem_address=$master_ip:$ds_port
log_level=INFO
in_cluster=true
master_addr=$master_ip:$(info_field "$info" global_scheduler_port)
mutual_tls_enable=false
mutual_tls_path=/root/mutual_tls_file
EOF
}

deploy_sandbox_runtime() {
    log "updating the dedicated py39 runtime metadata to use the nested AIO rootfs"
    docker cp "$ASSETS/sandbox_runtime.json" "$MASTER:/tmp/yr-gateway-sandbox-runtime.json"
    docker exec \
      -e YR_SERVER_ADDRESS=10.250.0.10:8889 \
      -e YR_VERIFY_FILE= \
      "$MASTER" bash -lc '
        yrcli deploy-language-rt \
          --function-json /tmp/yr-gateway-sandbox-runtime.json
    ' | tee "$RESULT_DIR/deploy-sandbox-runtime.log"
}

wait_actor_file() {
    local i
    for i in $(seq 1 120); do
        if docker exec "$MASTER" test -s /tmp/yr-gateway-actors.json 2>/dev/null; then
            docker cp "$MASTER:/tmp/yr-gateway-actors.json" "$RESULT_DIR/actors.json"
            return 0
        fi
        if ! docker exec "$MASTER" kill -0 "$(cat "$RESULT_DIR/actor.pid")" 2>/dev/null; then
            docker exec "$MASTER" bash -lc 'sed -n "1,260p" /tmp/yr-gateway-actor.log' >&2 || true
            die "actor driver exited before producing results"
        fi
        sleep 3
    done
    die "actors did not become ready"
}

route_for_instance() {
    local instance_id=$1 info=$2 master_ip etcd_port etcdctl
    master_ip="$(info_field "$info" master_ip)"
    etcd_port="$(info_field "$info" etcd_port)"
    etcdctl='$(python3 -c "from pathlib import Path; import yr; print(Path(yr.__file__).resolve().parent)")/third_party/etcd/etcdctl'
    docker exec -e INSTANCE_ID="$instance_id" "$MASTER" bash -lc "ETCDCTL_API=3 $etcdctl --endpoints=http://$master_ip:$etcd_port get /yr/route/business/yrk --prefix -w json" | \
        INSTANCE_ID="$instance_id" python3 -c '
import base64, json, os, sys
payload = json.load(sys.stdin)
for item in payload.get("kvs", []):
    value = json.loads(base64.b64decode(item["value"]))
    if value.get("instanceID") == os.environ["INSTANCE_ID"]:
        print(json.dumps(value, sort_keys=True))
        break
else:
    raise SystemExit("route not found")
'
}

assert_route_and_data_path() {
    local actor_json=$1 info=$2
    local instance_id edge_instance_id node_tag actor_host port expected_ip route route_host route_ip sandbox_id sandbox_ip body inspect_json
    instance_id="$(printf '%s' "$actor_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["instance_id"])')"
    edge_instance_id="$(INSTANCE_ID="$instance_id" python3 -c 'import os; value=os.environ["INSTANCE_ID"].replace("@", "-at-"); print("".join("-" if c in "/._" else c for c in value)[:200])')"
    node_tag="$(printf '%s' "$actor_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["node_tag"])')"
    actor_host="$(printf '%s' "$actor_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["hostname"])')"
    port="$(printf '%s' "$actor_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["port"])')"
    if [ "$node_tag" = node_tag2 ]; then
        expected_ip="$(container_ip "$WORKER2")"
        route_host="$WORKER2"
    else
        expected_ip="$(container_ip "$WORKER3")"
        route_host="$WORKER3"
    fi
    route="$(route_for_instance "$instance_id" "$info")"
    printf '%s\n' "$route" >"$RESULT_DIR/route-$node_tag.json"
    IFS=$'\t' read -r route_ip sandbox_id sandbox_ip < <(printf '%s' "$route" | python3 -c '
import json,sys
r=json.load(sys.stdin)
assert r.get("instanceStatus",{}).get("code") == 3, r
assert r.get("sandboxID"), r
assert r.get("sandboxIP"), r
print(r["nodeProxyAddress"].split(":")[0], r["sandboxID"], r["sandboxIP"], sep="\t")
')
    [ "$route_ip" = "$expected_ip" ] || die "$node_tag route points to $route_ip, expected $expected_ip"
    inspect_json="$(docker exec "$route_host" docker inspect "$sandbox_id")"
    printf '%s\n' "$inspect_json" >"$RESULT_DIR/inspect-$node_tag.json"
    INSPECT_JSON="$inspect_json" SANDBOX_IP="$sandbox_ip" python3 -c '
import json, os
d=json.loads(os.environ["INSPECT_JSON"])[0]
ips={n.get("IPAddress") for n in d["NetworkSettings"]["Networks"].values()}
assert os.environ["SANDBOX_IP"] in ips, (ips, os.environ["SANDBOX_IP"])
ports=d.get("HostConfig",{}).get("PortBindings") or {}
assert not ports, ports
'
    body="$(docker exec "$EDGE" curl -fsS --retry 5 --retry-delay 1 "http://127.0.0.1:8080/$edge_instance_id/$port/probe?node=$node_tag")"
    printf '%s\n' "$body" >"$RESULT_DIR/response-$node_tag.json"
    BODY="$body" ACTOR_HOST="$actor_host" python3 -c 'import json,os; d=json.loads(os.environ["BODY"]); assert d["hostname"] == os.environ["ACTOR_HOST"], d; assert d["path"].startswith("/probe?node="), d'
    log "$node_tag verified: route=$expected_ip:8443 sandbox=$sandbox_ip:$port id=$sandbox_id"
}

assert_l4_path() {
    local actor_json=$1 instance_id edge_instance_id port actor_host body
    instance_id="$(printf '%s' "$actor_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["instance_id"])')"
    edge_instance_id="$(INSTANCE_ID="$instance_id" python3 -c 'import os; value=os.environ["INSTANCE_ID"].replace("@", "-at-"); print("".join("-" if c in "/._" else c for c in value)[:200])')"
    port="$(printf '%s' "$actor_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["port"])')"
    actor_host="$(printf '%s' "$actor_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["hostname"])')"
    docker exec -d "$EDGE" bash -lc "YR_ROOT=\$(python3 -c 'from pathlib import Path; import yr; print(Path(yr.__file__).resolve().parent)'); \"\$YR_ROOT/data_plane/bin/yr-data-plane-forward\" port-forward 127.0.0.1:8080 '$edge_instance_id' '$port' 127.0.0.1:19090 >/tmp/yr-data-plane-forward.log 2>&1"
    for _ in $(seq 1 30); do
        body="$(docker exec "$EDGE" curl -fsS -m 3 http://127.0.0.1:19090/raw-l4 2>/dev/null || true)"
        [ -n "$body" ] && break
        sleep 1
    done
    BODY="$body" ACTOR_HOST="$actor_host" python3 -c 'import json,os; d=json.loads(os.environ["BODY"]); assert d["hostname"] == os.environ["ACTOR_HOST"], d; assert d["path"] == "/raw-l4", d'
    log "standard HTTP CONNECT adapter verified through Edge port 8080"
}

run_e2e() {
    trap cleanup EXIT INT TERM
    build_gateway
    build_frontend
    build_image
    start_cluster
    local info actor_pid actor1 actor2
    info="$(master_info)"
    prepare_driver "$info"
    deploy_sandbox_runtime
    docker exec -d "$MASTER" bash -lc 'python3 /usr/local/lib/yr-gateway-e2e/echo_actor.py >/tmp/yr-gateway-actor.log 2>&1 & echo $! >/tmp/yr-gateway-actor.pid'
    docker exec "$MASTER" cat /tmp/yr-gateway-actor.pid >"$RESULT_DIR/actor.pid"
    wait_actor_file
    actor1="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))[0]))' "$RESULT_DIR/actors.json")"
    actor2="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))[1]))' "$RESULT_DIR/actors.json")"
    assert_route_and_data_path "$actor1" "$info"
    assert_route_and_data_path "$actor2" "$info"
    assert_l4_path "$actor1"
    docker exec "$EDGE" curl -fsS http://127.0.0.1:18080/metrics >"$RESULT_DIR/edge.metrics"
    docker exec "$WORKER2" curl -fsS http://127.0.0.1:18443/metrics >"$RESULT_DIR/worker2.metrics"
    docker exec "$WORKER3" curl -fsS http://127.0.0.1:18443/metrics >"$RESULT_DIR/worker3.metrics"
    local cache_entries
    cache_entries="$(awk '$1 == "data_plane_edge_frontend_route_cache_entries" {print int($2)}' "$RESULT_DIR/edge.metrics")"
    [ "${cache_entries:-0}" -ge 2 ] || die "Edge cache does not contain both routes"
    log "PASS: 3 nodes, 2 owning workers, direct HTTP and standard CONNECT all used sandbox IP without hostPort"
    log "evidence: $RESULT_DIR"
}

run_sdk_e2e() {
    trap cleanup EXIT INT TERM
    build_gateway
    build_frontend
    build_rrt_runtime
    build_image
    build_sdk_images
    start_cluster
    deploy_sandbox_runtime
    load_sdk_runtime_image
    docker rm -f "$SDK_DRIVER" >/dev/null 2>&1 || true
    log "running live sandbox-sdk matrix through Frontend, Edge and Node Proxy"
    docker run --name "$SDK_DRIVER" \
        --network "$NETWORK" \
        -e YR_SERVER_ADDRESS=10.250.0.10:8889 \
        -e YR_GATEWAY_ADDRESS=10.250.0.20:8443 \
        -e YR_GATEWAY_TLS=1 \
        -e YR_TUNNEL_SSL_VERIFY=0 \
        -e YR_SANDBOX_IMAGE="$SDK_RUNTIME_IMAGE" \
        -e YR_E2E_RESULT=/results/sandbox-sdk-result.json \
        -v "$RESULT_DIR:/results" \
        "$SDK_DRIVER_IMAGE" | tee "$RESULT_DIR/sandbox-sdk.log"

    docker exec "$EDGE" curl -fsS http://127.0.0.1:18080/metrics >"$RESULT_DIR/edge-sdk.metrics"
    docker exec "$MASTER" curl -fsS http://127.0.0.1:18443/metrics >"$RESULT_DIR/master-sdk.metrics"
    docker exec "$WORKER2" curl -fsS http://127.0.0.1:18443/metrics >"$RESULT_DIR/worker2-sdk.metrics"
    docker exec "$WORKER3" curl -fsS http://127.0.0.1:18443/metrics >"$RESULT_DIR/worker3-sdk.metrics"
    python3 - "$RESULT_DIR" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
result = json.loads((root / "sandbox-sdk-result.json").read_text())
assert not result["failed"], result
edge = (root / "edge-sdk.metrics").read_text()
physical = next(float(line.split()[1]) for line in edge.splitlines() if line.startswith("data_plane_edge_frontend_h2_physical_connections "))
assert physical >= 1, edge
node_bytes = 0.0
for name in ("master", "worker2", "worker3"):
    metrics = (root / f"{name}-sdk.metrics").read_text()
    node_bytes += sum(float(line.split()[1]) for line in metrics.splitlines() if line.startswith("data_plane_node_proxy_bytes_"))
assert node_bytes > 0, node_bytes
print(f"verified Edge H2 connections={physical:g}, Node relayed bytes={node_bytes:g}")
PY
    log "PASS: sandbox-sdk command, filesystem, copy-file, PTY, tunnel and port-forwarding matrix"
    log "evidence: $RESULT_DIR"
}

run_idle_timeout_e2e() {
    trap cleanup EXIT INT TERM
    build_gateway
    build_frontend
    build_rrt_runtime
    build_image
    build_sdk_images
    start_cluster
    deploy_sandbox_runtime
    load_sdk_runtime_image
    docker rm -f "$SDK_DRIVER" >/dev/null 2>&1 || true
    log "holding a Rust Edge/Node CONNECT stream across the sandbox idle timeout"
    docker run --name "$SDK_DRIVER" \
        --network "$NETWORK" \
        --entrypoint python \
        -e YR_SERVER_ADDRESS=10.250.0.10:8889 \
        -e YR_GATEWAY_ADDRESS=10.250.0.20:8080 \
        -e YR_NODE_METRICS=10.250.0.10:18443,10.250.0.12:18443,10.250.0.13:18443 \
        -e YR_SANDBOX_IMAGE="$SDK_RUNTIME_IMAGE" \
        -e YR_E2E_RESULT=/results/idle-timeout-result.json \
        -v "$RESULT_DIR:/results" \
        "$SDK_DRIVER_IMAGE" /usr/local/bin/idle_timeout_e2e.py | tee "$RESULT_DIR/idle-timeout.log"

    docker exec "$EDGE" curl -fsS http://127.0.0.1:18080/metrics >"$RESULT_DIR/edge-idle.metrics"
    for node in "$MASTER" "$WORKER2" "$WORKER3"; do
        docker exec "$node" curl -fsS http://127.0.0.1:18443/metrics \
            >"$RESULT_DIR/$node-idle.metrics"
    done
    python3 - "$RESULT_DIR/idle-timeout-result.json" <<'PY'
import json
import sys

result = json.load(open(sys.argv[1], encoding="utf-8"))
assert result.get("running_after_hold") is True, result
assert result.get("probe_after_hold") == "HTTP/1.0 200", result
assert result.get("reclaimed_after_close") is True, result
assert sum(result.get("active_streams_by_node", {}).values()) >= 1, result
assert result["actual_hold_seconds"] > result["idle_timeout_seconds"], result
print(json.dumps(result, sort_keys=True))
PY
    log "PASS: active data-plane stream cancelled idle reclamation; close restarted idle timeout"
    log "evidence: $RESULT_DIR"
}

case "${1:-run}" in
    build-gateway) build_gateway; build_frontend ;;
    build-image) build_image ;;
    run) run_e2e ;;
    sdk-run) run_sdk_e2e ;;
    idle-run) run_idle_timeout_e2e ;;
    *) die "usage: $0 {build-gateway|build-image|run|sdk-run|idle-run}" ;;
esac
