ARG BASE_IMAGE=yr-local-aio:latest
FROM ${BASE_IMAGE}

COPY functionsystem/functionsystem/build/bin/function_proxy /tmp/yr-gateway-e2e/function_proxy
COPY functionsystem/runtime-launcher/bin/runtime/runtime-launcher /tmp/yr-gateway-e2e/runtime-launcher
COPY data-plane-gateway/target/linux-aarch64-release/yr-node-proxy /tmp/yr-gateway-e2e/yr-node-proxy
COPY data-plane-gateway/target/linux-aarch64-release/yr-edge-frontend /tmp/yr-gateway-e2e/yr-edge-frontend
COPY data-plane-gateway/target/linux-aarch64-release/yr-data-plane-forward /tmp/yr-gateway-e2e/yr-data-plane-forward
COPY data-plane-gateway/target/linux-aarch64-release/rrt-runtime /tmp/yr-gateway-e2e/rrt-runtime
COPY data-plane-gateway/target/linux-aarch64-release/faasfrontend.so /tmp/yr-gateway-e2e/faasfrontend.so
COPY data-plane-gateway/target/linux-aarch64-release/goruntime /tmp/yr-gateway-e2e/goruntime
COPY deploy/sandbox/docker/services.yaml /tmp/yr-gateway-e2e/services.yaml

COPY api/python/yr/cli /tmp/yr-gateway-e2e/cli

RUN set -eu; \
    python3 -m pip install --no-cache-dir \
      --index-url https://mirrors.huaweicloud.com/repository/pypi/simple \
      --trusted-host mirrors.huaweicloud.com tomli tomli-w; \
    YR_ROOT="$(python3 -c 'from pathlib import Path; import yr; print(Path(yr.__file__).resolve().parent)')"; \
    if [ -d "${YR_ROOT}/functionsystem/bin" ]; then FS_ROOT="${YR_ROOT}/functionsystem"; \
    elif [ -d "${YR_ROOT}/inner/functionsystem/bin" ]; then FS_ROOT="${YR_ROOT}/inner/functionsystem"; \
    else echo "functionsystem directory not found below ${YR_ROOT}" >&2; exit 1; fi; \
    FRONTEND_SO="$(find "${YR_ROOT}" -path '*/faasfrontend/faasfrontend.so' -print -quit)"; \
    test -n "${FRONTEND_SO}"; \
    install -m 0755 /tmp/yr-gateway-e2e/faasfrontend.so "${FRONTEND_SO}"; \
    install -m 0755 /tmp/yr-gateway-e2e/goruntime "${YR_ROOT}/runtime/service/go/bin/goruntime"; \
    install -m 0755 /tmp/yr-gateway-e2e/function_proxy "${FS_ROOT}/bin/function_proxy"; \
    install -m 0755 /tmp/yr-gateway-e2e/runtime-launcher "${FS_ROOT}/bin/runtime-launcher"; \
    install -m 0755 /tmp/yr-gateway-e2e/runtime-launcher /openyuanrong/runtime-launcher; \
    install -d "${YR_ROOT}/data_plane/bin"; \
    install -m 0755 /tmp/yr-gateway-e2e/yr-node-proxy "${YR_ROOT}/data_plane/bin/yr-node-proxy"; \
    install -m 0755 /tmp/yr-gateway-e2e/yr-edge-frontend "${YR_ROOT}/data_plane/bin/yr-edge-frontend"; \
    install -m 0755 /tmp/yr-gateway-e2e/yr-data-plane-forward "${YR_ROOT}/data_plane/bin/yr-data-plane-forward"; \
    install -m 0755 /tmp/yr-gateway-e2e/rrt-runtime /usr/local/bin/rrt-runtime; \
    install -m 0644 /tmp/yr-gateway-e2e/services.yaml /openyuanrong/services.yaml; \
    sed -i 's#entrypoint: "set -e; export LD_LIBRARY_PATH=.*openyuanrong_rrt.runtime_path()).*"#entrypoint: "/usr/local/bin/rrt-runtime"#' /openyuanrong/services.yaml; \
    cp -a /tmp/yr-gateway-e2e/cli/. "${YR_ROOT}/cli/"; \
    rm -rf /tmp/yr-gateway-e2e

# The base AIO image still supervises a legacy Traefik process and etcd seed.
# This E2E deliberately exposes Frontend and Edge directly, so remove both
# programs instead of merely avoiding their ports.
RUN sed -i \
    -e '/^\[program:traefik\]/,/^$/d' \
    -e '/^\[program:seed-traefik-etcd\]/,/^$/d' \
    /etc/supervisor/supervisord.conf

COPY --chmod=0755 data-plane-gateway/tests/aio_3node/start-master.sh /usr/local/lib/yr-gateway-e2e/start-master.sh
COPY --chmod=0755 data-plane-gateway/tests/aio_3node/start-worker.sh /usr/local/lib/yr-gateway-e2e/start-worker.sh
COPY --chmod=0755 data-plane-gateway/tests/aio_3node/start-edge.sh /usr/local/lib/yr-gateway-e2e/start-edge.sh
COPY --chmod=0755 data-plane-gateway/tests/aio_3node/echo_actor.py /usr/local/lib/yr-gateway-e2e/echo_actor.py
