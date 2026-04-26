# YuanRong CI — Helm Deployment

One-click deployment of the CI infrastructure:

- **bazel-remote** cache (hostPath on the target cluster node or scheduler-selected node)
- **agent-stack-k8s** (Buildkite agent for K8s, upstream chart)
- **gitcode-webhook-relay** (optional GitCode -> Buildkite API bridge)
- **Secrets** templates (obs-credentials, gitcode-webhook-relay-auth)

## Prerequisites

1. `kubectl` access to the CCE cluster
2. `helm` ≥ 3.10
3. Secrets already exist (or set `secrets.*.create=true` + fill values)
4. bazel-remote image mirrored to SWR (see NOTES.txt)

## Install

```bash
# 1. Deploy yuanrong-ci (bazel-remote + namespace)
helm upgrade --install yuanrong-ci deploy/helm/yuanrong-ci/ \
  -n default \
  --create-namespace

# 2. Deploy Linux amd64 agent-stack-k8s (upstream chart)
helm upgrade --install agent-stack-k8s oci://ghcr.io/buildkite/helm/agent-stack-k8s \
  --version 0.40.0 \
  -f deploy/helm/agent-stack-k8s-values.yaml \
  --set agentToken="${BUILDKITE_AGENT_TOKEN}" \
  -n default

# 3. Deploy Linux arm64 agent-stack-k8s (optional, same default queue)
helm upgrade --install agent-stack-k8s-arm64 oci://ghcr.io/buildkite/helm/agent-stack-k8s \
  --version 0.40.0 \
  -f deploy/helm/agent-stack-k8s-arm64-values.yaml \
  --set agentToken="${BUILDKITE_AGENT_TOKEN}" \
  -n default
```

## Key knobs in values.yaml

| Key | Default | Description |
|-----|---------|-------------|
| `global.buildNode` | `""` | Optional node name for pinning bazel-remote |
| `bazelRemote.maxSizeGb` | `200` | Max cache size |
| `bazelRemote.hostPath` | `/mnt/paas` | Host directory for cache |
| `bazelRemote.image` | SWR mirror | Must be accessible without Docker Hub |

## GitCode webhook relay

Enable the relay when direct GitCode -> Buildkite webhook delivery is not sufficient for
merge-request events or when you need branch/action filtering before triggering a build.

```bash
helm upgrade --install yuanrong-ci deploy/helm/yuanrong-ci/ \
  -n default \
  --set gitcodeWebhookRelay.enabled=true \
  --set gitcodeWebhookRelay.ingress.enabled=true \
  --set gitcodeWebhookRelay.ingress.host=ci-webhook.example.com \
  --set secrets.gitcodeWebhookRelayAuth.create=true \
  --set secrets.gitcodeWebhookRelayAuth.buildkiteApiToken="${BUILDKITE_API_TOKEN}" \
  --set secrets.gitcodeWebhookRelayAuth.webhookSignatureSecret="${GITCODE_WEBHOOK_SECRET}"
```

GitCode WebHook settings:

| Field | Value |
|-----|-----|
| URL | `https://<ingress-host>/webhook/gitcode` |
| Content-Type | `application/json` |
| Events | `Commit Event`, `Pull Request Event` |
| Secret | Prefer a signature secret (`X-GitCode-Signature-256`) |

The relay validates the GitCode signature or token, filters branches/actions, and then
calls the Buildkite REST API with the normalized `branch`, `commit`, and `env` payload.

By default it is configured for **merge-only** triggering:

- `push` events do not start builds
- only merge-request action `merge` is accepted
- merge events build the **target branch commit after merge**

If the cluster has no Ingress controller, expose the relay with a Service:

```bash
helm upgrade --install yuanrong-ci deploy/helm/yuanrong-ci/ \
  -n default \
  --set gitcodeWebhookRelay.enabled=true \
  --set gitcodeWebhookRelay.service.type=LoadBalancer
```

## Migrate existing cluster resources

The cluster already has manually-created resources. This chart **takes ownership**
of the `bazel-remote` deployment once installed. Existing secrets are not
re-created by default (`secrets.*.create: false`).
