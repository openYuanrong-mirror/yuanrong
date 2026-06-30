# Minimal Python SDK And FaaS Smoke Test

## Purpose

Provide a minimal, reproducible single-node validation flow that runs inside the `compile` container and verifies basic Python SDK and Python FaaS paths work after code changes.

## Prerequisites

1. Run inside the `compile` container
2. Build a fresh wheel in `output/openyuanrong-*.whl`
3. Ensure the `compile` container does not already have a conflicting YuanRong runtime

## Quick Start

```bash
docker exec compile bash -lc 'cd /home/wyc/code/ant/yuanrong/example/minimal-python && bash run_smoke.sh'
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FRONTEND_PORT` | `8888` | Frontend HTTP port |
| `FRONTEND_GRPC_PORT` | `31223` | Frontend gRPC port |
| `META_SERVICE_PORT` | `31111` | Meta service port |
| `ETCD_PORT` | `32379` | Embedded etcd client port |
| `ETCD_PEER_PORT` | `32380` | Embedded etcd peer port |
| `DEPLOY_PATH` | `/tmp/yr-minimal-python-smoke` | Temporary runtime deploy path |
| `PYTHON_BIN` | auto-discovered | Python interpreter used for wheel install and SDK smoke |

Example with a different frontend port:

```bash
docker exec compile bash -lc 'cd /home/wyc/code/ant/yuanrong/example/minimal-python && FRONTEND_PORT=18888 bash run_smoke.sh'
```

## What Is Tested

### SDK Smoke Tests

1. Runtime initialization with `yr.init(Config(...))`
2. Stateless invocation with `@yr.invoke`
3. Stateful invocation with `@yr.instance`
4. Object store round-trip with `yr.put()` and `yr.get()`
5. Negative case that must raise instead of silently succeeding

### FaaS Smoke Tests

1. Function deployment through `POST /admin/v1/functions`
2. Text payload invocation through `POST /invocations/{tenant}/{namespace}/{function}/`
3. JSON payload invocation through the same frontend HTTP path
4. Runtime environment visibility in the handler response
5. Repeated invocation success

## No Auth Required

This smoke flow starts YuanRong with:

- `--enable_iam_server false`
- `--enable_function_token_auth false`

It does not depend on Traefik, Casdoor, or Keycloak.

## Runtime Notes

- The script installs the built wheel into the current Python environment
- `yr` is discovered after wheel installation
- Health checks use `/healthz`
- FaaS deploy metadata is generated dynamically so `codePath` is always the current repo path

## Files

- `run_smoke.sh` discovers Python and `yr`, installs the wheel, starts the runtime, and runs the smoke flow
- `services.yaml` defines the minimal Python yrlib service used by SDK smoke tests
- `sdk_smoke.py` uses `@yr.invoke`, `@yr.instance`, `yr.put`, and `yr.get`
- `faas_smoke.sh` deploys via `/admin/v1/functions` and invokes via `/invocations/...`
- `faas/handler.py` is the minimal Python FaaS handler
