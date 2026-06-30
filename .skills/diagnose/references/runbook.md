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

# YuanRong Service Diagnostics Runbook

## Architecture Reference

```
User Request
    │
    ▼
Traefik (8888, HTTPS)  —  entry: https://<traefik-host>:8888/
    │
    ▼
Frontend goruntime (PID ~621, loads faasfrontend.so via libruntime)
    │  gRPC bidi stream (MessageStream) → port 22773
    ▼
function_proxy (PID ~298, C++ litebus actor framework)
    │  gRPC → port 22770
    ▼
function_master (PID ~109)
    │
    ▼
etcd (akernel-etcd.akernel.svc.cluster.local:2379)
    │
    ├── datasystem_worker (PID ~295, port 31501)
    └── iam_server (PID ~204, port 31112)
```

### Kubernetes Cluster Topology

- **Namespace**: `akernel` — YuanRong runtime pods
- **Namespace**: `akernel-monitor` — Grafana/Loki/Prometheus/Tempo stack
- **Namespace**: `monitoring` — Prometheus Operator, alertmanager, node-exporter
- **Master pod**: `akernel-master-0` (IP: <master-pod-ip>, Node: <node-ip>)
- **Node pods**: `akernel-node-{suffix}` (~34 nodes, all in `akernel` namespace)
- **etcd pod**: `akernel-etcd-0`
- **Image**: `swr.cn-east-3.myhuaweicloud.com/openyuanrong/cluster-all-in-one:<tag>`

### Key Ports

| Component | Port | Protocol | Notes |
|-----------|------|----------|-------|
| Traefik | 8888 | HTTPS | Gateway entry |
| function_master | 22770 | gRPC | Scheduling, instance management |
| function_proxy | 22772 | HTTP | `/local-scheduler/healthy` health check |
| function_proxy | 22773 | gRPC | Bidi stream from goruntime (frontend) |
| function_proxy | 22774 | gRPC | Session gRPC port |
| datasystem_worker | 31501 | gRPC/TCP | Data storage |
| iam_server | 31112 | HTTP | Auth/token |
| OTel Collector | 4317 | gRPC | Trace export (localhost inside pod) |

### Process PIDs (approximate, on master pod)

| Process | Typical PID | Role |
|---------|-------------|------|
| `function_master` | ~109 | Scheduling decisions, etcd state |
| `iam_server` | ~204 | Token auth |
| `datasystem_worker` | ~295 | Shared memory / data tier |
| `function_proxy` | ~298 | Instance lifecycle, runtime connection |
| `goruntime` (frontend) | ~621 | HTTP gateway, loads faasfrontend.so |
| `goruntime` (scheduler) | ~639 | Scheduler driver |
| `meta_service` | ~687 | Metadata management |

### Log Files Inside Pod (`/home/yuanrong/master/log/`)

| File | What it contains |
|------|-----------------|
| `{node_id}-function_master.log` | Scheduling, instance state machine |
| `{node_id}-function_proxy.log` | Runtime connections, invocation dispatch |
| `{node_id}-faas_frontend_std.log` | HTTP request handling, health checks |
| `{node_id}-function_master_std.log` | function_master stdout |
| `runtime-{id}.out` | Individual runtime instance stdout (user code / libruntime) |

Older logs are compressed: `{node_id}-function_proxy.{timestamp}.log.gz`

## kubectl Setup

```bash
# Install if not present (binary is NOT persistent — reinstall after reboot)
curl -sk https://dl.k8s.io/release/v1.28.0/bin/linux/amd64/kubectl -o /tmp/kubectl && chmod +x /tmp/kubectl

# All kubectl commands use this pattern:
K="KUBECONFIG=~/.kube/yr.yaml /tmp/kubectl"

# List pods
eval "$K get pods -n akernel -o wide"

# Exec into master
eval "$K exec akernel-master-0 -n akernel -- <cmd>"

# Exec into a node pod
eval "$K exec akernel-node-94fbc -n akernel -- <cmd>"
```

Kubeconfig contexts: `external` (default, `<external-host>:5443` no TLS verify),
`internal` (<internal-host>:5443), `externalTLSVerify` (<external-host>:5443 with cert).

## Phase 1: Grafana — Locate Anomaly

### 1.1 Access Grafana

```
URL:  https://<grafana-host>:8888/grafana/
User: admin
Pass: admin (or credentials in LastPass "Grafana Admin")
```

Datasource UIDs: `prometheus`, `loki`, `tempo`

**API access pattern** (use in bash via curl):
```bash
G="https://<grafana-host>:8888/grafana"
A="admin:admin"
curl -sk -u "$A" "$G/api/..."
```

### 1.2 Prometheus Queries (via API)

Proxy base: `$G/api/datasources/proxy/uid/prometheus/api/v1/`

**YuanRong-specific metrics:**

| Metric | What it shows |
|--------|--------------|
| `function_invocations_total` | Request count by `function_name`, `http_code`, `akernel_env` |
| `function_invocation_duration_seconds_{bucket,sum,count}` | Latency histogram |
| `yr_instance_count{node_id=...}` | Running instances per node |
| `yr_cluster_instance_total_count` | Total cluster instances |
| `yr_cluster_cpu_capacity_vmillicore` / `yr_cluster_cpu_allocatable_vmillicore` | CPU capacity |
| `yr_cluster_memory_capacity_mb` / `yr_cluster_memory_allocatable_mb` | Memory capacity |
| `yr_nodes_cpu_capacity_vmillicore` / `yr_nodes_cpu_allocatable_vmillicore` | Per-node CPU |

**Span metrics from Tempo** (derived from traces):

| Metric | What it shows |
|--------|--------------|
| `traces_spanmetrics_calls_total` | Call count by span/service |
| `traces_spanmetrics_latency_{bucket,sum,count}` | Latency from trace spans |
| `traces_service_graph_request_total` | Service-to-service request count |
| `traces_service_graph_request_{client,server}_seconds_*` | Service graph latency |

**Useful PromQL patterns for diagnosis:**

```promql
# Error rate (5xx)
sum(rate(function_invocations_total{http_code=~"5.."}[5m])) /
sum(rate(function_invocations_total[5m]))

# p95 latency
histogram_quantile(0.95, sum(rate(function_invocation_duration_seconds_bucket[5m])) by (le, function_name))

# Instance count drop (sudden loss of capacity)
yr_cluster_instance_total_count{akernel_env="default"}

# Per-node instance count (find outlier nodes)
yr_instance_count{akernel_env="default"}
```

**Run a PromQL query:**
```bash
curl -sk -u "$A" -G "$G/api/datasources/proxy/uid/prometheus/api/v1/query" \
  --data-urlencode 'query=yr_cluster_instance_total_count' | python3 -m json.tool
```

**Query over time window:**
```bash
curl -sk -u "$A" -G "$G/api/datasources/proxy/uid/prometheus/api/v1/query_range" \
  --data-urlencode 'query=sum(rate(function_invocations_total[5m]))' \
  --data-urlencode "start=$(date -d '1 hour ago' +%s)" \
  --data-urlencode "end=$(date +%s)" \
  --data-urlencode "step=60" | python3 -m json.tool
```

### 1.3 Loki Log Queries

Proxy base: `$G/api/datasources/proxy/uid/loki/loki/api/v1/`

**Available label dimensions:**

| Label | Values |
|-------|--------|
| `service_name` | `yuanrong-faasfrontend`, `yuanrong-faasscheduler`, `yuanrong-functionsystem`, `yuanrong-datasystem`, `yuanrong-stdlogs`, `akernel-imagemanager` |
| `component_name` | `function_master`, `function_proxy`, `function_agent` |
| `node_name` | `akernel-master-0`, `akernel-node-{suffix}` (34 nodes) |
| `process_name` | `frontend-process`, `scheduler-process` |
| `akernel_env` | `default` |

**Log stream mapping:**
- `{service_name="yuanrong-functionsystem", component_name="function_proxy"}` → function_proxy logs
- `{service_name="yuanrong-functionsystem", component_name="function_master"}` → function_master logs
- `{service_name="yuanrong-faasfrontend"}` → frontend HTTP handler logs
- `{service_name="yuanrong-stdlogs"}` → runtime instance stdout (user code + libruntime)
- `{service_name="yuanrong-faasscheduler"}` → scheduler driver logs

**Loki LogQL patterns for diagnosis:**

```logql
# Errors on a specific node
{service_name="yuanrong-functionsystem", component_name="function_proxy", node_name="akernel-master-0"} |= "ERROR"

# Connection failures (gRPC stream)
{service_name="yuanrong-functionsystem"} |= "Read failed"

# Instance exit failures
{service_name="yuanrong-functionsystem", component_name="function_proxy"} |= "failed to exit instance"

# libruntime reconnection / stream reset
{service_name="yuanrong-stdlogs"} |= "Read failed from function-proxy"

# All errors in time window on master
{service_name=~"yuanrong-.*", node_name="akernel-master-0"} |~ "ERROR|FATAL|panic"
```

**Run a Loki query:**
```bash
curl -sk -u "$A" -G "$G/api/datasources/proxy/uid/loki/loki/api/v1/query_range" \
  --data-urlencode '{service_name="yuanrong-functionsystem",component_name="function_proxy"} |= "ERROR"' \
  --data-urlencode "limit=50" \
  --data-urlencode "start=$(date -d '1 hour ago' +%s)000000000" \
  --data-urlencode "end=$(date +%s)000000000" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for s in d.get('data',{}).get('result',[]):
    for ts, line in s.get('values',[]):
        print(line[:300])
"
```

### 1.4 Tempo Trace Queries

Proxy base: `$G/api/datasources/proxy/uid/tempo/`

**Services instrumented:** `frontend`, `function_master`, `function_proxy`

**Key span names (from traces):**
- `frontend`: `/serverless/v1/posix/instance/invoke`, `/serverless/v1/posix/instance/kill`, `http.invoke`
- `function_master`: scheduling-related spans
- `function_proxy`: instance lifecycle spans

**Search recent traces:**
```bash
# Recent traces
curl -sk -u "$A" "$G/api/datasources/proxy/uid/tempo/api/search?limit=20" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for t in d.get('traces',[]):
    print(t.get('traceID'), t.get('rootServiceName'), t.get('rootTraceName'), t.get('durationMs'))
"

# Traces by service
curl -sk -u "$A" "$G/api/datasources/proxy/uid/tempo/api/search?service.name=function_proxy&limit=10" | python3 -m json.tool

# Get full trace details
curl -sk -u "$A" "$G/api/datasources/proxy/uid/tempo/api/traces/<traceID>" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for batch in d.get('batches',[]):
    svc = {a['key']:a.get('value',{}) for a in batch.get('resource',{}).get('attributes',[])}
    print('Service:', svc.get('service.name',{}).get('stringValue'))
    for scope in batch.get('scopeSpans',[]):
        for span in scope.get('spans',[]):
            print(' ', span.get('name'), span.get('status',{}))
"
```

### 1.5 What to Extract from Grafana

- **First error timestamp** — correlate with any deployment or infra event
- **Which service_name / node_name** shows errors first
- **Error message pattern** — maps to specific code path
- **Instance count drop** — sudden crash vs gradual degradation
- **Trace showing high latency or error status** — which span is the bottleneck

## Phase 2: kubectl — Inspect Pod State

### 2.1 Setup

```bash
# Ensure kubectl binary present
ls /tmp/kubectl || curl -sk https://dl.k8s.io/release/v1.28.0/bin/linux/amd64/kubectl -o /tmp/kubectl && chmod +x /tmp/kubectl

K="KUBECONFIG=~/.kube/yr.yaml /tmp/kubectl"
```

### 2.2 Check Pod Status

```bash
# All akernel pods
eval "$K get pods -n akernel -o wide"

# Check if master had restarts
eval "$K describe pod akernel-master-0 -n akernel" | grep -E "Restart|Last State|Reason"

# Check events
eval "$K get events -n akernel --sort-by=.lastTimestamp" | tail -20
```

### 2.3 Check Process Status

```bash
eval "$K exec akernel-master-0 -n akernel -- ps aux" | grep -E 'function_proxy|function_master|goruntime|datasystem'

# Check if a specific PID is alive
eval "$K exec akernel-master-0 -n akernel -- cat /proc/298/status" | grep -E "^Name:|^State:|^Threads:"
```

### 2.4 Check Process Threads

```bash
# Thread count for function_proxy (PID ~298)
eval "$K exec akernel-master-0 -n akernel -- sh -c 'ls /proc/298/task | wc -l'"

# Thread states — look for 'D' (uninterruptible) which signals deadlock
eval "$K exec akernel-master-0 -n akernel -- sh -c \
  'for tid in \$(ls /proc/298/task); do cat /proc/298/task/\$tid/status 2>/dev/null | grep -E \"^Name:|^State:\"; done'"
```

Normal: threads in `S (sleeping)` on futex/epoll.
Abnormal: `D (uninterruptible disk sleep)` = I/O deadlock.

### 2.5 Check Ports

```bash
# Port → hex conversion: 22770=58F2, 22772=58F4, 22773=58F5, 31501=7B0D, 31112=7978
eval "$K exec akernel-master-0 -n akernel -- cat /proc/net/tcp" | awk '{print $2}' | grep -E "^[^s]" | while read hex; do
  port=$((16#${hex##*:})); echo $port
done | sort -n | uniq

# Health check function_proxy
eval "$K exec akernel-master-0 -n akernel -- sh -c 'wget -qO- http://<master-pod-ip>:22772/local-scheduler/healthy 2>&1 || echo FAILED'"
```

### 2.6 Check Logs Inside Pod

```bash
# Log directory
eval "$K exec akernel-master-0 -n akernel -- ls /home/yuanrong/master/log/"

# Tail current function_proxy log
eval "$K exec akernel-master-0 -n akernel -- tail -100 /home/yuanrong/master/log/akernel-master-0-function_proxy.log"

# Search for errors in time window (within current log file)
eval "$K exec akernel-master-0 -n akernel -- sh -c \
  'grep -E \"ERROR|FATAL|failed|panic\" /home/yuanrong/master/log/akernel-master-0-function_proxy.log | tail -50'"

# Runtime instance logs (user code + libruntime)
eval "$K exec akernel-master-0 -n akernel -- sh -c \
  'ls /tmp/yr_sessions/latest/ | head -20'"
eval "$K exec akernel-master-0 -n akernel -- sh -c \
  'cat /tmp/yr_sessions/latest/<runtime-id>.out | tail -50'"
```

### 2.7 Check External Dependencies

```bash
# etcd — check connectivity from master pod
eval "$K exec akernel-master-0 -n akernel -- sh -c \
  'wget -qO- http://akernel-etcd.akernel.svc.cluster.local:2379/health 2>&1'"

# OTel Collector — trace export endpoint (localhost:4317)
eval "$K exec akernel-master-0 -n akernel -- sh -c \
  'cat /proc/net/tcp6 | awk \"{print \\\$2}\" | grep :10E5 | wc -l'"
# 10E5 hex = 4325 dec ≈ looking for port 4317 = 0x10DD
```

## Phase 3: Source Code — Trace Failure Path

### 3.1 Map Symptom to Code

| Symptom (from logs) | Code Area |
|---------------------|-----------|
| `Read failed from function-proxy` (in yuanrong-stdlogs) | `src/libruntime/fsclient/grpc/fs_intf_grpc_client_reader_writer.cpp` |
| gRPC stream dead, no reconnection | `src/libruntime/clientsmanager/clients_manager.cpp` |
| Proxy connection options | `src/libruntime/fsclient/fs_intf_impl.cpp` |
| Request retry exhaustion | `src/libruntime/fsclient/fs_intf_impl.h` (RetryWrapper) |
| Health check failure (`componentshealth`) | `frontend/pkg/frontend/clusterhealth/clusterhealth.go` |
| Trace export blocking | `functionsystem/.../trace/trace_manager.cpp` |
| `failed to exit instance, code(1003)` | `functionsystem/.../instance_control/instance_ctrl_actor.cpp:859` |
| `cancel schedule from InstanceManagerActor` | `functionsystem/.../domain_sched_srv_actor.cpp` |

### 3.2 Trace the Call Chain

1. Extract the exact error line from Loki (`service_name`, `component_name`, `code_filepath` label)
2. Grep for file/function in source: `grep -r "error string" /home/wyc/code/ant/yuanrong/`
3. Trace backwards: what conditions trigger that error
4. Cross-check with trace span that corresponds to the same operation

### 3.3 Common Failure Patterns

**Pattern 1: Silent gRPC stream death**
- `yuanrong-stdlogs` shows `Read failed from function-proxy`
- TCP alive but peer stopped processing → no keepalive → no detection → no reconnect
- Fix check: `isKeepAlive` in `ReaderWriterClientOption`

**Pattern 2: Blocking trace export**
- `BatchSpanProcessor` Export() blocks when OTel Collector (localhost:4317) is down
- Background exporter thread stuck → actor thread pool exhausted
- Fix check: `BatchSpanProcessorOptions` timeout, exporter endpoint health

**Pattern 3: Actor thread exhaustion**
- litebus worker threads all in `D` state
- New invocations queue indefinitely
- Fix check: thread count vs expected, what syscall each thread is blocked in

**Pattern 4: Instance exit failure (code 1003)**
- `function_proxy` logs `failed to exit instance, code(1003)` at `instance_ctrl_actor.cpp:859`
- Instance state machine stuck, can't finalize
- Check: datasystem_worker health, runtime process still alive

## Phase 4: Root Cause & Fix

### 4.1 Confirm Root Cause

- Does the code-level bug explain ALL observed symptoms?
- Does the timing match? (first Loki error ts vs first Prometheus drop)
- Does the failure mode match? (e.g., no reconnection → persistent outage, not flapping)

### 4.2 Propose Fix

1. Minimal fix — address the immediate bug
2. Defense in depth — secondary detection (timeout, watchdog)
3. Blast radius — verify fix doesn't break normal operation

### 4.3 Verification

```bash
# Build the changed component
docker exec compile bash -lc 'cd /home/wyc/code/ant/yuanrong && bazel build //src/libruntime:libruntime'

# Run unit tests
docker exec compile bash -lc 'cd /home/wyc/code/ant/yuanrong && bash build.sh -t'

# After deploy: confirm via Grafana
# - Error rate drops to 0
# - Instance count stable
# - No new ERROR lines in Loki
```
