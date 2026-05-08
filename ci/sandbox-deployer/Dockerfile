FROM swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev/compile-ubuntu2004:v20260428_cmake33110

ARG HELM_VERSION=3.15.4
ARG KUBECTL_VERSION=1.30.8
ARG TARGETARCH

ENV PIP_BREAK_SYSTEM_PACKAGES=1 \
    PYTHONUNBUFFERED=1

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
    /opt/buildtools/python3.9/bin/python3.9 --version; \
    kubectl version --client=true; \
    helm version --short
