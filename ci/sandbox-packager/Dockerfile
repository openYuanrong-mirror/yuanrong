# syntax=docker/dockerfile:1.4

FROM docker:27.5.1-dind

ARG HELM_VERSION=3.15.4
ARG KUBECTL_VERSION=1.30.8
ARG TARGETARCH

ENV DOCKER_DRIVER=overlay2 \
    DOCKER_TLS_CERTDIR="" \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PYTHONUNBUFFERED=1

RUN apk upgrade --no-cache && \
    apk add --no-cache \
    bash \
    ca-certificates \
    coreutils \
    curl \
    expat \
    findutils \
    git \
    gzip \
    py3-packaging \
    py3-pip \
    py3-setuptools \
    py3-wheel \
    python3 \
    tar

RUN set -e; \
    case "${TARGETARCH}" in \
      amd64) HELM_ARCH="amd64"; KUBECTL_ARCH="amd64" ;; \
      arm64) HELM_ARCH="arm64"; KUBECTL_ARCH="arm64" ;; \
      *) echo "Unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://get.helm.sh/helm-v${HELM_VERSION}-linux-${HELM_ARCH}.tar.gz" -o /tmp/helm.tar.gz; \
    tar -xzf /tmp/helm.tar.gz -C /tmp; \
    install -m 0755 "/tmp/linux-${HELM_ARCH}/helm" /usr/local/bin/helm; \
    rm -rf /tmp/helm.tar.gz "/tmp/linux-${HELM_ARCH}"; \
    curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 300 \
      "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/${KUBECTL_ARCH}/kubectl" \
      -o /usr/local/bin/kubectl; \
    chmod +x /usr/local/bin/kubectl; \
    kubectl version --client=true; \
    helm version --short

RUN python3 -m pip install --no-cache-dir \
      -i https://mirrors.huaweicloud.com/repository/pypi/simple \
      --trusted-host mirrors.huaweicloud.com \
      esdk-obs-python
