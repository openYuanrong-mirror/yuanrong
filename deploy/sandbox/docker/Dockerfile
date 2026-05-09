ARG CONTROLPLANE_IMAGE=yr-controlplane
FROM ${CONTROLPLANE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive
ARG TRAEFIK_VERSION=v3.1.2

RUN apt-get update && apt-get install -y --no-install-recommends \
        gnupg \
        iptables \
        supervisor \
        uidmap \
    && rm -rf /var/lib/apt/lists/*

RUN install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc && \
    chmod a+r /etc/apt/keyrings/docker.asc && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$UBUNTU_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list && \
    apt-get update && apt-get install -y --no-install-recommends \
        containerd.io \
        docker-buildx-plugin \
        docker-ce \
        docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

ENV CONTAINER_EP="unix:///var/run/runtime-launcher.sock" \
    DOCKER_HOST="unix:///var/run/docker.sock"

COPY aio-yr-runtime.tar /opt/runtime-images/aio-yr-runtime.tar
COPY --from=deploy services.yaml /openyuanrong/services.yaml
COPY --from=deploy traefik /openyuanrong/traefik/
COPY --from=deploy docs/TRAEFIK_ETCD.md /openyuanrong/docs/TRAEFIK_ETCD.md
COPY --from=deploy supervisord.conf /etc/supervisor/supervisord.conf
COPY --from=deploy dockerd-entrypoint.sh /usr/local/bin/dockerd-entrypoint.sh
COPY --from=deploy supervisord-entrypoint.sh /usr/local/bin/supervisord-entrypoint.sh
COPY --from=deploy start-yuanrong.sh /usr/local/bin/start-yuanrong.sh
COPY --from=deploy seed-traefik-etcd.sh /usr/local/bin/seed-traefik-etcd.sh

RUN chmod +x /openyuanrong/runtime-launcher /usr/local/bin/dockerd-entrypoint.sh /usr/local/bin/supervisord-entrypoint.sh /usr/local/bin/start-yuanrong.sh /usr/local/bin/seed-traefik-etcd.sh

RUN wget -qO /tmp/traefik.tar.gz https://github.com/traefik/traefik/releases/download/${TRAEFIK_VERSION}/traefik_${TRAEFIK_VERSION}_linux_amd64.tar.gz || \
    curl -sL -o /tmp/traefik.tar.gz https://github.com/traefik/traefik/releases/download/${TRAEFIK_VERSION}/traefik_${TRAEFIK_VERSION}_linux_amd64.tar.gz && \
    tar -xzf /tmp/traefik.tar.gz -C /tmp traefik && \
    install -m 0755 /tmp/traefik /usr/local/bin/traefik && \
    rm -f /tmp/traefik /tmp/traefik.tar.gz

WORKDIR /root

ENV YR_SERVER_ADDRESS="127.0.0.1:8888" \
    YR_IAM_ADDRESS="127.0.0.1:31112" \
    YR_CLIENT_AUTH_TYPE="one-way" \
    YR_SERVER_NAME="openyuanrong.org" \
    YR_ENABLE_TLS="false" \
    YR_IN_CLUSTER="false" \
    ENABLE_TOKEN="false"

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/supervisord-entrypoint.sh"]
