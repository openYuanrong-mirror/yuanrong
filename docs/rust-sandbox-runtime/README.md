# rrt · Rust Sandbox Runtime

> openYuanrong 沙箱专用、Rust 原生、薄控制面 daemon（`rrt-runtime`）的**单一权威文档**：定位、架构、接入、构建、部署、契约。
> 对外 HTTP/WS API 与 SDK 用法见 [`../features/sandbox-rest-api.md`](../features/sandbox-rest-api.md)。

---

## 1. 定位

给 openYuanrong 加一个**沙箱专用、Rust 原生、薄控制面 daemon**，作为新的 sandbox runtime peer：
只提供「进程 / 文件 / shell / 端口 / 生命周期 / tunnel」通用原语，**不加载用户代码、不链 libruntime、不背数据系统**。
用户代码 = 沙箱里的普通进程/镜像。架构上是往已有「多 runtime」抽象里加一个 peer（注册 `runtimeType`），不是新盒子。对标 e2b `envd` + substrate `ateom`。

相比 Python + libruntime 的三位一体 runtime（平台运行时 = 语言运行时 = SDK 通道焊在一个进程），rrt 在沙箱场景去掉了用不上的多语言宿主与数据系统，更薄更快；绑定问题（cgo/pybind/jni）直接消失。

---

## 2. 架构与运行模式

`rrt-runtime`（`src/bin/rrt-runtime.rs`）按环境变量分三种模式：

| 模式 | 触发 | 入口 | 用途 |
|------|------|------|------|
| **runtime-mode**（默认） | 无 | `runtime::run()` | 生产：连 function-proxy 的 RuntimeRPC worker + HTTP invoke server + 可选 tunnel |
| **http-only** | `RRT_HTTP_ONLY=1` | `serve_http_only(port, token)` | 隔离验证：仅起 HTTP 原子操作 server |
| **tunnel-only** | `RRT_TUNNEL_ONLY=1` | `serve_tunnel_only(ws, http)` | 隔离验证：仅起原生 reverse tunnel server（供真 TunnelClient 互通） |

runtime-mode（`run()`）并发提供三条面：
- **RuntimeRPC worker**：连 `--rt_server_address`，做生命周期握手让实例 ready（见 §5）。
- **HTTP invoke server**（`RRT_HTTP_PORT`，默认 50090）：`/invoke` + `/healthz`，经 sandboxRouter direct 暴露。
- **reverse tunnel**（设 `RRT_TUNNEL_WS_PORT` 时启用）：Port A（WS）+ Port B（HTTP），与 HTTP server **并发**（此前二者互斥，已打通）。

端口约定见 [REST 文档 §2](../features/sandbox-rest-api.md#2-端口与鉴权约定)。

---

## 3. 源码结构

代码落位 `api/rust/`（与 `api/python|go|java|cpp` 平级）。workspace 下单包 `rrt-daemon`（tokio + serde + tonic）。

```
api/rust/rrt-daemon/
├── Cargo.toml / Cargo.lock
├── src/
│   ├── bin/rrt-runtime.rs       # 模式入口（§2）
│   ├── runtime/                 # ← 当前实现（runtime-mode）
│   │   ├── mod.rs               #   parse_args / run() / serve_http_only / serve_tunnel_only
│   │   ├── dispatch.rs          #   sandbox_invoke action 归一与分发（核心）
│   │   ├── cmd.rs               #   进程原语（exec/start/poll/wait/kill/list/stdin）
│   │   ├── fs.rs                #   文件原语（read/write/list/stat/...）
│   │   ├── bash.rs              #   持久 bash 会话
│   │   ├── stream.rs            #   sandbox_stream_*（file / tar 流）
│   │   ├── tunnel.rs            #   原生 reverse tunnel（Port A/B，JSON Frame）
│   │   ├── httpserver.rs        #   HTTP /invoke /healthz 手写 HTTP/1.1
│   │   ├── codec.rs / pyval.rs  #   yr cross-language 序列化（msgpack/cloudpickle 互通）
│   │   └── activity.rs          #   忙闲/活动信号（idle 上报基础）
│   └── {process,filesystem,port,health,lib,main}.rs   # ← 旧 P1 gRPC daemon（50088，已废弃/dead-code）
└── proto/                       # RuntimeRPC / posix proto
```

> **现状 vs 历史**：`src/runtime/*` 是当前 runtime-mode 实现；`src/{process,filesystem,port,health}.rs` 是早期 P1 的 gRPC daemon（`Process/Health/Filesystem/Port` on 50088），sandboxRouter 代理不了 gRPC，已不在主链路。

---

## 4. 接入机制（如何被拉起）

1. **runtime-launcher**（functionsystem，宿主侧 DinD）按 `services.yaml` 的 sandbox slot `docker run` 沙箱容器，注入启动命令。
2. sandbox slot 的 `bootstrap.entrypoint` 设端口环境变量并 `exec` wheel 内的 `rrt-runtime`：
   ```
   set -e; export RRT_HTTP_PORT=50090; export RRT_TUNNEL_WS_PORT=8765;
   exec "$(python -c 'import openyuanrong_rrt;print(openyuanrong_rrt.runtime_path())')"
   ```
   一行 diff 即可在 python/rust 后端间切换。**严禁 `yaml.safe_dump` 重写 `services.yaml`**（破坏格式 → function_master `-p` 加载失败），只做精确行级编辑。
3. rrt-runtime 进 runtime-mode，连 `--rt_server_address` 完成 RuntimeRPC 握手 → 实例 ready。

**职责边界（实证）**：
- **exec**（`yrcli exec` / 终端）：function_proxy 从容器外 `docker exec` 注入，**runtime 不参与**；rrt 只需保证容器有 `/bin/sh` 且进程保活。
- **port-forward**：frontend gateway（traefik）`/{instance}/{port}` 转发到容器内监听端口，**runtime 不参与**。
- **reverse tunnel + 原子操作**：**唯一需要 rrt 实现的数据面**。

---

## 5. RuntimeRPC 硬契约（runtime-mode 必须满足）

逐跳实测啃下的契约（`golden case` akernel create+ping 经 rrt 端到端绿）：

1. **连接标识（gRPC metadata）**：`MessageStream` 带 `instance_id`、`runtime_id`、`source_id`(=instance_id)、`dst_id="function-proxy"`。`instance_id = runtime_id.strip_prefix("runtime-").rsplit_once('-').0`。错则 `Unauthenticated`。
2. **握手序列**：收 `heartbeatReq` **必须回 `heartbeatRsp`**（否则 proxy 判死、反复重启容器）；`callReq{is_create=true}` → 回 `CallResult{code:0}` 建实例；`callReq{is_create=false}` → 方法 dispatch。
3. **方法名**：`callReq.args[0].value` = protobuf `resources.MetaData`，方法名在 `functionMeta.functionName`（field3）。
4. **结果不背 datasystem**：client 设 `bypass_datasystem=True` → 结果内联；rrt 回 `CallResult.smallObjects=[{id=returnObjectIDs[0], value=<序列化结果>}]`。不设则 driver 查 datasystem 卡 `WaitBeforeGet`。
5. **结果路由回 driver**：`CallResult.instanceID = callReq.senderID`（senderID→CallResult.instanceID）。
6. **返回值序列化**：yr cross-language 格式 `[8B metadata header][8B msgpack_size header][msgpack_data][可选 cloudpickle]`。简化：`[16 字节 0] + msgpack(value)`，`split_buffer` 据 metadata=0&size=0 推断 `CROSS_LANGUAGE`。akernel 方法返回值（str/int/dict）用 `rmp_serde::to_vec_named` 即可，不依赖 python。

数据面（`cmd_run`/`fs_*`/`bash_*`/`sandbox_stream_*`）同模式：解 `args[1:]` 参数 → 复用 Process/Filesystem/Bash/Stream 原语 → `yr_serialize` 结果回。action 归一见 [REST 文档 §5](../features/sandbox-rest-api.md#5-action-词表两条数据面共用)。

---

## 6. 构建

> 只在编译镜像里构建 rrt，禁止主机直接编。镜像：`swr.cn-southwest-2.../yuanrong-dev/compile-ubuntu2004-rust:<tag>`（rust + protoc）。

```bash
# 直接 cargo（编译镜像内 / compile_rrt 容器）
cd api/rust/rrt-daemon && cargo build --release --bin rrt-runtime
# 产物：api/rust/target/release/rrt-runtime（workspace target）

# 全量测试
cargo test -p rrt-daemon
```

### 6.1 CI：独立并行 step

rrt 不依赖任何其他组件，故在 CI 中**独立成并行 step**（`.buildkite/pipeline.dynamic.yml`）：

- `:crab: Build RRT amd64/arm64`（key `build-rrt-<arch>`，**无 `depends_on`，从 t=0 与主构建并行**）：`cargo build --release` + 打 `openyuanrong-rrt` wheel + 上传 artifact/OBS。
- 主构建（Build X86 / Build arm）设 **`BUILD_SKIP_RUST=1`**（`build.sh` 据此从 bazel targets 剥掉 `//api/rust:yr_rust_pkg`），rrt 离开其关键路径。
- Build Image / Build Runtime 经 `buildkite-agent artifact download`（按 arch pattern 全局拉）取 wheel，并 `depends_on build-rrt-<arch>`。
- 复用 `/mnt/paas` cargo 目录 + **sccache**（content-addressed rustc 缓存，跨 build/节点保温）。

> 效果：把 rrt 的 ~48min 冷编译从主构建关键路径尾部移走 → Build X86 关键路径约腰斩（实测 ~47min → ~24min；Build RRT 热缓存 ~24s 并行）。

### 6.2 静态链接

发布产物默认 `x86_64-unknown-linux-musl`，static-pie / statically linked，避免依赖 runtime 镜像 glibc/libgcc（构建环境需 `rustup target add x86_64-unknown-linux-musl`）。

---

## 7. 部署（AIO 分发链路）

`rrt-runtime` 不经宿主 volume mount 注入，而是**随 wheel + 镜像固化分发**：

```
cargo build --release --bin rrt-runtime
  → openyuanrong-rrt wheel: openyuanrong_rrt/<rrt-runtime>（runtime_path() 解析）
  → Dockerfile.runtime: pip install openyuanrong-*.whl → yr-runtime 镜像内置
  → aio-yr-runtime 镜像 → aio-yr:latest 内置 /opt/runtime-images/aio-yr-runtime.tar
  → AIO 启动时 inner dockerd `docker load`
  → runtime-launcher 按 services.yaml 拉起 runtime 容器 → exec rrt-runtime
```

关键约定：
- `openyuanrong-rrt` 是 Python-agnostic 的 `py3-none-manylinux` wheel，仅承载 rrt-runtime 二进制；`runtime_path()` 解析其路径，`RRT_RUNTIME_BIN` 可覆盖。
- runtime 镜像通过 `pip install` 安装 rrt；entrypoint 经 `openyuanrong_rrt.runtime_path()` 定位二进制（见 §4）。
- AIO 主容器不直接跑裸 `rrt-runtime`；由内层 dockerd 拉 runtime 容器运行。

详细 AIO 拓扑（5 层镜像、supervisord 进程树、DinD 桥接、bootstrap.root）见 git 历史的 `2026-06-11-aio-explained.md`（已并入本文要点）。

---

## 8. 生命周期与忙闲

- 容器级 Start/Checkpoint/Delete 由 functionsystem `runtime-launcher`（宿主侧，对标 ateom）负责，**rrt 不重造**，只做容器内原语。
- `activity.rs` 采集活动信号（active ops / streams / `last_active_at`），为 rrt → proxy `IdleMgr` 的 idle 上报与 suspend/wakeup 策略打基础（设计在演进中）。

---

## 9. 验收与本地复现

- **单测/集成**：`cargo test -p rrt-daemon`（对真实 server/fs/端口断言）。
- **rrt-direct e2e**：`sandbox-sdk/tests/e2e_rrt_direct.py`（CI `run_rrt_direct_e2e`）；K8S 部署+验证见 git 历史 `sandbox-rrt-deploy-and-verify`（要点：traefik `router` entrypoint :28888 → frontend sandboxRouter :8080 → rrt :50090；成功标志 `_direct_disabled is False`）。
- **tunnel 数据面隔离复现**（绕过 router/集群，秒级）：
  ```bash
  # 编译镜像内起 tunnel-only server
  RRT_TUNNEL_ONLY=1 RRT_TUNNEL_WS_PORT=8765 RRT_TUNNEL_HTTP_PORT=8766 rrt-runtime
  # host 用真 TunnelClient 直连 ws://127.0.0.1:8765，curl http://127.0.0.1:8766/ 验往返
  ```
  直连即复现 → 锁定问题在 rrt/SDK 协议而非 router（router 仅透传 WS 帧）。

---

## 10. 给其它 AI / reviewer 的提醒

- **以代码 + 本文为准**：历史按日期命名的 plan/handoff 文档记录的是「当时打算怎么做」，已并入本文并删除；个别旧决策（如「spawn python tunnel_server」「无应用层鉴权」「gRPC on 50088」）**已被推翻**，当前真相是原生 Rust tunnel + control-port JWT 鉴权 + HTTP invoke on 50090。
- **改 `services.yaml` 只做行级编辑**，禁止 `yaml.safe_dump` 重写。
- **构建只在编译镜像里做**。
