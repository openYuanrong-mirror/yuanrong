# YuanRong Development Guide

以第一性原理！从原始需求和问题本质出发，不从惯例或模板触发。
1、不要假设我清楚自己想要什么。动机或目标不清晰时，停下来讨论；
2、目标清晰但路径不是最短的，直接告诉我并建议更好的办法；
3、遇到问题追根因，不打补丁。每个决策都要能回答"为什么"；
4、输出说重点，砍掉一切不改变决策的信息。

## Build Dependencies

Build order matters. Components are ordered by dependency:

```
datasystem ──────┬──► functionsystem
                 ├──► yuanrong
                 └──► dashboard

frontend ────────► yuanrong

dashboard ───────► yuanrong

functionsystem ─► yuanrong
```

**Dependency rules:**
- `A -> B` means A depends on B (build B first, then A)
- When modifying a component, rebuild all components that depend on it

**Build order (least to most dependent):**
1. `yuanrong` (core runtime)
2. `functionsystem`, `dashboard` (depend on yuanrong)
3. `datasystem` (depends on functionsystem, yuanrong, dashboard)
4. `frontend` (depends on yuanrong)

**To get a complete openyuanrong package:** build `yuanrong` last. It is the integration point that bundles all components into the final package.

## Compile Container

All builds depend on the `compile` container. It is defined in `ci/openeuler/docker-compose.yml` and supports both x86_64 and aarch64 architectures.

**Start the container (x86_64 by default):**

```bash
cd /home/wyc/code/ant/yuanrong/ci/openeuler
docker-compose up -d
```

**Start on aarch64 (ARM):**

```bash
cd /home/wyc/code/ant/yuanrong/ci/openeuler
ARCH=aarch64 docker-compose up -d
```

**Container name:** `compile`

**Images:**
- x86_64: `swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev/compile_x86:2.1`
- aarch64: `swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev/compile_aarch64:2.1`

**What it provides:**
- Go 1.24.1, Java JDK 8, Maven 3.9.11
- Python 3.9 / 3.10 / 3.11 / 3.12 / 3.13 (from source)
- Bazel 6.5.0, Ninja, CMake, protobuf
- Node.js 20.19.0, npm

**Port:** 8888 (frontend HTTP)

**Build inside the container:**

```bash
docker exec compile bash -lc 'cd /home/wyc/code/ant/yuanrong && make all'
```

## Project Structure

- `yuanrong/` - Core runtime (C++, Python, Java, Go APIs)
- `functionsystem/` - Function scheduling and management
- `datasystem/` - Distributed data system (multi-level cache)
- `frontend/` - API gateway (HTTP, WebSocket, JWT auth)
- `dashboard/` - Web management UI
- `api/` - Cross-language API definitions

## Testing

```bash
# Run all tests
bash build.sh -t

# Run tests with specific filter
bash build.sh -t -T "TestName*"

# Generate coverage report
bash build.sh -c

# Run with AddressSanitizer
bash build.sh -S address

# Run with ThreadSanitizer
bash build.sh -S thread

# System tests (requires deployment)
cd test/st
bash test.sh -l all  # Run all language tests
bash test.sh -l cpp  # C++ tests only
bash test.sh -l python  # Python tests only
bash test.sh -l java  # Java tests only
bash test.sh -l go  # Go tests only
```

### Direct Bazel Commands

```bash
# Build specific targets
bazel build //api/python:yr_python_pkg
bazel build //api/java:yr_java_pkg
bazel build //api/cpp:yr_cpp_pkg
bazel build //api/go:yr_go_pkg

# Run specific tests
bazel test //test/...
bazel test //api/python/yr/tests/...
bazel test //api/java:java_tests
```

## Smoke Tests

Python smoke tests located at `test/smoke/minimal-python/`:

| File | Description |
|------|-------------|
| `run_smoke.sh` | Discovers Python and `yr`, installs wheel, starts runtime, runs smoke flow |
| `sdk_smoke.py` | SDK smoke: `yr.init`, `@yr.invoke`, `@yr.instance`, `yr.put`, `yr.get` |
| `faas_smoke.sh` | FaaS smoke: deploys function via `/admin/v1/functions`, invokes via `/invocations/...` |
| `faas/handler.py` | Minimal Python FaaS handler |
| `services.yaml` | Minimal Python yrlib service definition |

Run inside `compile` container:

```bash
docker exec compile bash -lc 'cd /home/wyc/code/ant/yuanrong/test/smoke/minimal-python && bash run_smoke.sh'
```
