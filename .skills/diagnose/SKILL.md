<!--
  Copyright (c) Huawei Technologies Co., Ltd. 2024-2025. All rights reserved.

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
-->

---
name: diagnose
description: Diagnose YuanRong service unavailability using Grafana dashboards, kubectl pod inspection, logs, and source code. Use when user reports service down or abnormal behavior.
metadata:
  short-description: Diagnose service unavailability via Grafana/kubectl/logs
---

# Diagnose Service Unavailability

Systematic approach to locate root cause when a YuanRong component becomes unavailable.

For detailed runbook, see `references/runbook.md`

## Quick Start

When user reports a service issue, gather:

1. **Time window** — exact start/end time of the incident
2. **Symptom** — which component, what behavior (unavailable, slow, error)
3. **Topology** — which pod, which node IP

## Execution Flow

```
1. Grafana — locate anomaly in metrics/logs
2. kubectl — inspect pod state, processes, ports
3. Source code — trace the exact code path that failed
4. Root cause — identify the bug, propose fix
```

## Key Access

- Grafana: `https://<grafana-host>:8888/grafana/` — credentials in LastPass "Grafana Admin"
- kubectl: `KUBECONFIG=~/.kube/yr.yaml /tmp/kubectl -n akernel exec <pod> -- <cmd>`
  - Binary: `/tmp/kubectl` (install if missing: `curl -sk https://dl.k8s.io/release/v1.28.0/bin/linux/amd64/kubectl -o /tmp/kubectl && chmod +x /tmp/kubectl`)
  - Kubeconfig: `~/.kube/yr.yaml` (contexts: `external` default, `internal`, `externalTLSVerify`)
- Pod logs: `/home/yuanrong/master/log/` inside pod (NOT `/tmp/yr_sessions/` — that's inside runtime instances)
- Component health: `curl http://<pod-ip>:22772/local-scheduler/healthy`

## Rules

- **Do NOT rush to recovery** — locate root cause first
- **Do NOT do destructive operations** in kubectl (no restart, no kill, no delete)
- Use `kubectl exec` for read-only inspection only
- When checking ports, use the actual node IP (not 127.0.0.1)
- Correlate Grafana metrics with kubectl findings before reading source code
