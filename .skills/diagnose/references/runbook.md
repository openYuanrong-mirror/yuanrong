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
Traefik (8888)
    │
    ▼
Frontend (goruntime, PID ~3600, loads faasfrontend.so)
    │  gRPC bidi stream (MessageStream)
    ▼
function_proxy (PID ~300, C++ process, litebus actor framework)
    │
    ▼
function_master (PID ~100)
    │
    ▼
etcd
```

### Key Ports

| Component | Port | Protocol | Path |
|-----------|------|----------|------|
| Traefik | 8888 | HTTPS | Gateway entry |
| Frontend | 8888 (via Traefik) | HTTP | `/serverless/v1/componentshealth`, `/healthz` |
| function_proxy | 22772 | HTTP | `/local-scheduler/healthy` |
| function_proxy | 22770 | gRPC | Bidi stream from goruntime |
| OTel Collector | 4317 | gRPC | Trace export |

### Component Health Chain

- `/serverless/v1/componentshealth` → checks functiontask, instancemanager, functionaccessor
- `/healthz` → basic liveness
- function_proxy health → `curl <node-ip>:22772/local-scheduler/healthy`

## Phase 1: Grafana — Locate Anomaly

### 1.1 Access Grafana

```
URL: https://<traefik-ip>:8888/grafana/
Credentials: refer to deployment config or environment variables
```

Use `WebFetch` or `mcp__web_reader__webReader` tool to read Grafana dashboards.

### 1.2 Key Dashboards to Check

1. **Request rate / error rate** — look for spikes or drops in the incident time window
2. **Latency (p50/p95/p99)** — look for degradation
3. **Component health** — which component reported unhealthy

### 1.3 Loki Log Queries

Search logs in the incident time window for:
- Error messages from the affected component
- Connection failures, timeouts, reconnection attempts
- gRPC status codes (UNAVAILABLE, DEADLINE_EXCEEDED)

### 1.4 What to Extract

- Exact timestamps of first error and recovery
- Which component failed first (frontend, function_proxy, etc.)
- Error messages that indicate the failure mode

## Phase 2: kubectl — Inspect Pod State

### 2.1 Access Pod

```bash
kubectl -n akernel exec akernel-master-0 -- bash
```

### 2.2 Check Process Status

```bash
# Are key processes running?
ps aux | grep -E 'function_proxy|function_master|goruntime|faasfrontend'
```

### 2.3 Check Process Threads

```bash
# Get PID of interest, e.g. function_proxy PID 306
ls /proc/306/task | wc -l    # thread count
cat /proc/306/status | grep Threads

# Are any threads blocked?
ls /proc/306/task | xargs -I{} cat /proc/306/task/{}/status 2>/dev/null | grep -E "^Name:|^State:"
```

Normal state: all threads in `S (sleeping)` on futex/epoll — this is expected.
Abnormal: threads in `D (uninterruptible disk sleep)` indicates I/O deadlock.

### 2.4 Check Network Ports

```bash
# IMPORTANT: Use actual node IP, NOT 127.0.0.1
# Get node IP:
cat /etc/hosts | grep -v localhost

# Check if ports are listening
ss -tlnp | grep -E '22770|22772|8888'

# Health check
curl -v http://<node-ip>:22772/local-scheduler/healthy
```

### 2.5 Check Logs Inside Pod

```bash
# Logs location
ls /tmp/yr_sessions/

# Frontend stdout (goruntime communication layer output)
cat /tmp/yr_sessions/<session>/frontend_stdout.log

# function_proxy logs
cat /tmp/yr_sessions/<session>/function_proxy.log

# Search for errors in time window
grep -E 'ERROR|WARN|failed|timeout' /tmp/yr_sessions/<session>/*.log
```

### 2.6 Check External Dependencies

```bash
# etcd status
etcdctl endpoint health

# OTel Collector status
systemctl status otelcol-contrib  # or check process
curl http://localhost:4317  # should return gRPC response
```

## Phase 3: Source Code — Trace Failure Path

### 3.1 Map Symptom to Code

Based on findings from Phase 1-2, identify the failing code path:

| Symptom | Code Area |
|---------|-----------|
| gRPC stream dead, no reconnection | `src/libruntime/fsclient/grpc/fs_intf_grpc_client_reader_writer.cpp` |
| Keepalive not working | `src/libruntime/clientsmanager/clients_manager.cpp` |
| Proxy connection options | `src/libruntime/fsclient/fs_intf_impl.cpp` |
| Request retry exhaustion | `src/libruntime/fsclient/fs_intf_impl.h` (RetryWrapper) |
| Health check failure | `frontend/pkg/frontend/clusterhealth/clusterhealth.go` |
| Trace blocking | `functionsystem/.../trace/trace_manager.cpp` |
| Actor thread stuck | `functionsystem/.../instance_control/instance_ctrl_actor.cpp` |

### 3.2 Trace the Call Chain

1. Start from the error message found in logs
2. Grep for the error message in source code
3. Trace backwards: what conditions cause that error
4. Identify which component holds the blocked resource

### 3.3 Common Failure Patterns

**Pattern 1: Silent stream death**
- gRPC bidi stream Read() blocks indefinitely
- TCP connection alive but peer stopped processing
- No keepalive → no detection → no reconnection
- Check: `isKeepAlive` setting in `ReaderWriterClientOption`

**Pattern 2: Blocking trace export**
- BatchSpanProcessor Export() blocks gRPC
- If exporter endpoint (OTel Collector) down, export hangs until timeout
- OnEnd() is non-blocking (adds to queue), but background thread stuck
- Check: trace exporter endpoint, `BatchSpanProcessorOptions`

**Pattern 3: Actor thread exhaustion**
- litebus worker threads all blocked on sync I/O
- New requests queued but never picked up
- Check: thread count, what each thread is waiting on

## Phase 4: Root Cause & Fix

### 4.1 Confirm Root Cause

- Cross-reference: does the code-level bug explain ALL observed symptoms?
- Does the timing match? (e.g., OTel Collector restart time vs failure start)
- Does the failure mode match? (e.g., no reconnection explains persistent outage)

### 4.2 Propose Fix

1. Minimal fix first — address the immediate bug
2. Defense in depth — add secondary detection mechanisms
3. Consider blast radius — test that fix doesn't break normal operation

### 4.3 Verification

- Build: `docker exec compile bash -lc 'cd /home/wyc/code/ant/yuanrong && bazel build //src/libruntime:libruntime'`
- Deploy to test environment
- Simulate the failure condition (e.g., restart OTel Collector)
- Verify automatic recovery within expected timeframe
