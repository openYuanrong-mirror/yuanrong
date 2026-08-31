<!--
Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
Licensed under the Apache License, Version 2.0.
See the LICENSE file in this repository for the complete license text.
-->

# Sandbox 快照生命周期与本地恢复

本文面向 Sandbox SDK 用户和集群运维人员，说明当前已经实现的可复用 Snapshot、
Create-from-Snapshot、Pause/Resume、Failover 和 Reload。这里的“快照”不是一种统一寿命的
对象：可复用 Snapshot 是租户目录中的模板，Pause artifact 绑定被暂停的逻辑实例，local
recovery candidate 则只属于当前节点的 Failover/Reload 路径。

更底层的组件状态机与目录所有权见
[Sandbox 快照生命周期架构设计](./2026-08-13-sandbox-pause-resume-design.md)。Frontend 的原始
HTTP 契约见 [Sandbox lifecycle REST API](../../frontend/docs/sandbox-lifecycle-api.md)，FunctionSystem
的实现级约束见
[沙箱快照生命周期与同节点恢复](../../functionsystem/docs/superpowers/specs/2026-08-26-sandbox-local-snapshot-failover-design.md)
和
[大容量 Checkpoint 发布与目录所有权](../../functionsystem/docs/superpowers/specs/2026-08-29-large-firecracker-checkpoint-optimization-design.md)。

## 操作矩阵

| 操作 | 用户入口 | 源实例 | artifact 与逻辑权威 | 放置与成功结果 |
|---|---|---|---|---|
| 可复用 Snapshot | `sandbox.create_snapshot()` | 保持 RUNNING | FunctionMaster 保存租户隔离的 READY 目录；可多次使用 | local artifact 必须回源节点；DataSystem/OBS artifact 可在其他节点 materialize |
| Create-from-Snapshot | `Sandbox.create(snapshot_id, ...)` | 不受影响 | 创建新的逻辑 sandbox，不消费 Snapshot | 省略/非正 CPU 或 memory 复制对应完整源 Resource；正值替换；正 limit 覆盖目标；返回 RUNNING `Sandbox` |
| Pause | `sandbox.pause()` | 物理 runtime 在 checkpoint 后退出 | PAUSED `InstanceInfo` 持有 SnapshotInfo 和 TTL | local-only 固定源节点；分布式模式可重新调度；返回 `PauseResult` |
| Resume | `sandbox.resume()` | 从 PAUSED 恢复为 RUNNING | PAUSED version CAS 选出一个 RUNNING winner | 返回 winner 的 route、Proxy、node 和实际端口映射 |
| Failover | 创建时 `failover=True` | 故障后尝试替换物理 runtime | 只使用最新 local recovery candidate | 固定原 Proxy/Agent/node；无候选或恢复失败即失败，不冷启动 |
| Reload | `sandbox.reload()` | 主动替换当前物理 runtime | 与 Failover 共用 local recovery candidate 路径 | 固定原 Agent/node；返回 `bool`，不创建新逻辑 sandbox |

Pause/Resume 与 Create-from-Snapshot 都是控制面生命周期操作。Failover/Reload 是另一条同节点
恢复路径；设置 `failover=True` 不会创建候选，也不会把可复用 Snapshot 自动转换为 local recovery
candidate。selector 过滤的是 `localRecoveryCandidate=true`，不是单独的内部类型 discriminator；
内部 checkpoint 与 Pause artifact 都可能带该标记并成为“最新 local recovery candidate”。

## 前置条件

- 使用集群模式；本地模式的 legacy snapshot/snapstart 不受支持，`reload_instance()` 返回
  `False`。
- RRT 与 sandboxd runtime class 必须由 `ListAvailableRuntimes` 声明
  `supports_checkpoint_restore=true`。未知、尚未初始化或不支持的 runtime class 会在
  Checkpoint/Restore 前失败。
- FunctionAgent 与 RuntimeManager/sandboxd 必须看到同一个绝对 `checkpoint_dir`；
  FunctionProxy 不应挂载该目录。
- SDK、Frontend、FunctionMaster/Proxy、FunctionAgent、RuntimeManager、RRT 与 sandboxd 需要成套
  升级。新旧组件混部不能安全解释 storage mode、source node、timeout 和
  `StartRequest.checkpoint_info`。
- 使用 Python Sandbox SDK 时设置 `YR_SERVER_ADDRESS`、`YR_TOKEN` 和相应 TLS 配置；详细连接项见
  [Sandbox SDK README](../../sandbox-sdk/python/README.md)。
- 由内部 checkpoint 产生的 local recovery candidate 依赖 RRT checkpoint control socket。
  RuntimeManager 只有在运行环境设置
  `YR_RRT_CONTROL_SOCKET_PATH` 且 runtime 支持 checkpoint/restore 时才把该目录传入 sandbox。

## Sandbox SDK 用法

以下示例使用环境变量连接 Frontend：

```bash
export YR_SERVER_ADDRESS=frontend.example.com:443
export YR_TOKEN='your-jwt'
export YR_TLS=1
```

### 创建可复用 Snapshot

```python
from yr_sandbox import Sandbox

source = Sandbox(
    image="python:3.12-slim",
    name="snapshot-source",
    cpu=2000,
    memory=4096,
)
source.files.write("/workspace/state.txt", "ready\n")

snapshot = source.create_snapshot(
    name="python-base-v1",
    timeout_seconds=300,
)
print(snapshot.snapshot_id, snapshot.names)

same = Sandbox.get_snapshot(snapshot.snapshot_id)
items, next_page_token = Sandbox.list_snapshots(
    name="python-base-v1",
    page_size=20,
)
```

`create_snapshot()` 创建不失效的可复用 Snapshot，并让源 sandbox 保持运行。`name` 可省略；SDK
会拒绝空白名称。`timeout_seconds` 必须是 `1..3600` 的整数，默认 `300`。

FunctionMaster 的 durable record ID 由 tenant、source sandbox 与 request ID 派生，重放只校验记录
中的 create request ID。当前 record 没有持久 request fingerprint，因此 raw 调用方不能把同一
request ID 复用于不同 name/content；首次并发创建的 CAS loser 也可能直接返回 conflict。SDK 不向
调用方暴露该 ID，并为每次 `create_snapshot()` 生成新值。

创建可复用 Snapshot 时，FunctionSystem 会暂时阻止新的反向隧道 session，并拒绝已经存在活动
session 的实例。SDK 的 `checkpoint_inflight()` 作用域只降低预期重连日志噪声，不会让活动隧道
变成可 checkpoint 的连接，也不保证 HTTP、PTY、WebSocket 或反向隧道透明续接。

### 从可复用 Snapshot 创建

```python
# 直接传 SnapshotInfo 或 snapshot_id 字符串均可。
clone = Sandbox.create(
    snapshot,
    name="snapshot-clone",
)
print(clone.id)
print(clone.files.read("/workspace/state.txt"))

# 省略 CPU/memory 时复制对应完整源 Resource；正值替换。
larger = Sandbox.create(
    snapshot.snapshot_id,
    name="snapshot-clone-large",
    cpu=4000,
    memory=8192,
)
```

资源契约以 CPU 和 memory 的 presence/value 决定“复制还是替换”：`cpu` 或 `memory` 省略、为
`0`、`null` 或其他非正值时，FunctionSystem 复制 Snapshot 中对应的完整源 Resource，其中包括
该 Resource 已保存的 limit；正 CPU/memory 则创建目标 Resource 并替换源 Resource。正
`cpu_limit`/`mem_limit` 随后覆盖目标 Resource 的 limit。limit 没有独立的 presence/inheritance
开关，因此省略或 `0` 不能单独请求继承、清除或压制模板 limit；结果由对应 CPU/memory 是复制
还是替换决定。

Frontend create replay 比较解码后的 CreateRequest。JSON 中的省略、`0` 和 `null` 可能归一化为相同
标量，因此 raw 调用方不得把同一 `X-Request-Id` 复用于不同请求形状。

目标保留新的 sandbox ID、name、namespace 和普通 placement 输入。FunctionSystem 会应用 source
template 的 create options，但当前没有独立的 source/target tunnel-shape 校验。创建 tunnel-enabled
clone 时，调用方必须保证模板与新请求使用相同的 tunnel enablement 和控制端口；否则 Frontend
返回的 tunnel route 可能没有对应的 runtime provisioning。
随后 FunctionSystem 清除旧端口映射。local artifact 会附加 source node 的 required affinity；
分布式 artifact 可正常调度，源节点仅作为 Resume 的 preferred affinity。一次 Create 不消费
可复用 Snapshot：

```python
Sandbox.delete_snapshot(snapshot.snapshot_id)
```

删除前应确认没有后续 Create 依赖该目录。删除是租户范围的 catalog 与 artifact 清理，不会删除
已经从该 Snapshot 创建的 sandbox。

### Pause 与 Resume

```python
from yr_sandbox import PauseResult, ResumeResult, Sandbox

sandbox = Sandbox(
    image="python:3.12-slim",
    name="pausable",
    port_forwardings=[8080],
)
sandbox.files.write("/workspace/counter", "41\n")

paused: PauseResult = sandbox.pause(
    ttl_seconds=90_000,
    timeout_seconds=300,
)
print(paused.sandbox_id)
print(paused.snapshot_id, paused.size)
print(paused.state, paused.expires_at)

resumed: ResumeResult = sandbox.resume()
print(resumed.sandbox_id, resumed.state)
print(resumed.route_address, resumed.function_proxy_id, resumed.node_id)
print(dict(resumed.port_mappings))
print(sandbox.files.read("/workspace/counter"))
```

`pause()` 要求正整数 TTL，默认 `90000` 秒，并返回权威 `PauseResult`：

| 字段 | 含义 |
|---|---|
| `sandbox_id` | 原逻辑 sandbox ID |
| `snapshot_id` | Pause request ID；SDK 校验响应必须与本次 identity 相同 |
| `size` | artifact 中普通文件总字节数，必须大于 0 |
| `state` | 成功时为 `paused` |
| `expires_at` | Frontend 按有效 TTL 计算的 Unix 秒时间戳 |

`resume()` 返回 `ResumeResult`：

| 字段 | 含义 |
|---|---|
| `sandbox_id` / `state` | 同一逻辑 sandbox，成功时为 `running` |
| `route_address` | winner 的 runtime 路由地址 |
| `function_proxy_id` / `node_id` | winner 所在 Proxy 与节点 |
| `port_mappings` | container port 字符串到实际 host port 的映射 |

Resume 的成功边界是 RUNNING winner 已提交并返回完整 route；Frontend 本地 SandboxRouter cache 的
watch/read-through 收敛不在事务内。紧随其后的首次数据请求仍可能遇到短暂 route/backend 传播
窗口；对幂等操作可按业务策略重试，但不要因此再次发起新的 Resume identity。

### 自动 Failover

```python
sandbox = Sandbox(
    image="python:3.12-slim",
    name="same-node-failover",
    failover=True,
)
```

`failover=True` 只启用发生合格 runtime 故障时的恢复策略。恢复前必须已有同实例、同节点的最新
local recovery candidate。RRT 在启用了 control socket 的环境中提供本地 Unix HTTP 入口；例如镜像中
存在 `curl` 时可从 sandbox 内触发：

```bash
curl --fail --unix-socket "${YR_RRT_CONTROL_SOCKET_PATH}/rrt.sock" \
  -X POST http://localhost/checkpoint
```

成功响应为 `{"status":"completed"}`。该请求等待 FunctionProxy ACK、sandboxd handoff 和
`SnapStarted`，并生成只保存在本节点的 internal checkpoint candidate。它不会创建租户可见的
可复用 Snapshot，也不上传到 DataSystem/OBS。

故障时，FunctionProxy 从当前 Agent 的 LocalSnapshotView 选择最新候选，停止源 runtime，部署
候选并以同一逻辑实例的 version 刷新物理 identity。候选不存在、Agent 查询失败、metadata 无效
或 restore/deploy 失败都会进入现有失败清理路径；系统不会用空白冷启动冒充恢复成功。

### 主动 Reload

```python
if not sandbox.reload():
    raise RuntimeError("local recovery candidate is unavailable or reload failed")
```

Reload 不要求 `failover=True`，但仍要求当前 RUNNING 实例有同节点最新 local recovery
candidate。它与 Failover 共用恢复路径，保留逻辑 sandbox ID，替换 runtime/container/port 等
物理字段。`reload()` 对已关闭 sandbox 或 `SandboxError` 返回 `False`；需要 HTTP 状态和下游错误
消息时使用 raw REST。

Reload 在选出候选前失败不会停止源 runtime。当前实现没有为“源已停止后，后续 Reload 步骤
失败”增加独立持久化终态，调用方必须把 `False` 视为恢复未完成，而不是自动冷启动信号。

## Typed results

Sandbox SDK 的公开结果类型是不可变 dataclass：

```python
SnapshotInfo(snapshot_id: str, names: tuple[str, ...])
PauseResult(
    sandbox_id: str,
    snapshot_id: str,
    size: int,
    state: str,
    expires_at: int,
)
ResumeResult(
    sandbox_id: str,
    state: str,
    route_address: str,
    function_proxy_id: str,
    node_id: str,
    port_mappings: Mapping[str, int],
)
```

`Sandbox.create()` 返回新的 `Sandbox`，`Sandbox.reload()` 返回 `bool`，catalog delete 返回
`None`。

## Raw REST 摘要

除 SSE Create 外，Frontend 普通响应使用 envelope：

```json
{"code": 200, "message": "", "data": "<base64-encoded JSON>"}
```

下表中的结果是 `data` 解码后的 JSON：

| 操作 | 方法与路径 | body | 成功结果摘要 |
|---|---|---|---|
| Create | `POST /api/sandbox/v1/sandboxes` | 普通 create 字段；可含 `snapshotId`、`failover` | 非 SSE 为普通 envelope；SSE 的 final 包含 `sandboxId`、`status`、`requestId` |
| Create Snapshot | `POST /api/sandbox/v1/sandboxes/{id}/snapshots` | `name?`、`timeoutSeconds?` | `snapshotId`、`names` |
| Get/List Snapshot | `GET /api/sandbox/v1/snapshots/{snapshotID}` / `GET /api/sandbox/v1/snapshots` | list 使用 query | tenant-scoped catalog JSON |
| Delete Snapshot | `DELETE /api/sandbox/v1/snapshots/{snapshotID}` | 无 | catalog delete 结果 |
| Pause | `POST /api/sandbox/v1/sandboxes/{id}/pause` | `ttlSeconds`、`timeoutSeconds?` | `sandboxId`、`snapshotId`、`size`、`state`、`expiresAt` |
| Resume | `POST /api/sandbox/v1/sandboxes/{id}/resume` | `{}` | route、Proxy、node、port mappings |
| Reload | `POST /api/sandbox/v1/sandboxes/{id}/reload` | `{}` | `{"success":true}` |

Sandbox SDK 的 Create 发送 `Accept: text/event-stream`。Frontend 在成功建立 stream 后依次发送
`accepted` event（`status=creating`）、周期性 `: heartbeat` comment 和唯一 `final` event；final
的 `status` 为 `running`、`timeout` 或 `failed`，失败时还包含 `errorCode` 和 `message`。JSON
bind、body size 或其他 pre-stream 校验失败可以直接返回普通 HTTP error；一旦发送 accepted，后续
request replay/identity、调度、create timeout、下游校验与业务失败都在 final SSE 中表达，不能再用
最终 HTTP status 判断结果。raw HTTP 调用方不请求 SSE 时仍走普通 envelope。

request ID 规则按 route 区分：

- raw Create 使用可选 `X-Request-Id`；缺失时 Frontend 从 trace ID 派生并回显；
- Pause、Resume、Reload 和 reusable Snapshot create 必须提供 regex-valid
  `X-YR-Request-ID`，格式为：

```text
pause-[A-Za-z0-9][A-Za-z0-9._-]{0,127}
resume-[A-Za-z0-9][A-Za-z0-9._-]{0,127}
reload-[A-Za-z0-9][A-Za-z0-9._-]{0,127}
snapshot-[A-Za-z0-9][A-Za-z0-9._-]{0,127}
```

- Snapshot Get/List 不要求 lifecycle request header；
- Snapshot Delete 要求非空 `X-YR-Request-ID`。SDK 生成 `delete-snapshot-*`，但 Frontend delete
  handler 不对它应用上面四种 create/lifecycle prefix regex。

raw HTTP 的 Pause 在 `ttlSeconds` 省略或为 `0` 时使用 `90000`，只拒绝负数；SDK 则拒绝布尔、
零和负数。raw HTTP 的 Snapshot/Pause `timeoutSeconds` 默认 `300`，范围 `1..3600`。Create 的
`createTimeoutSeconds`/`scheduleTimeoutSeconds` 是创建预算，不是 lifecycle checkpoint timeout。

错误大致映射为：本地参数或 request ID 错误 `400`，下游业务拒绝 `409`，Frontend 到 Proxy
传输失败 `503`，权威响应不完整 `500`。Reload 错误响应的 decoded `data` 仍可包含
`{"success":false}`。

## Legacy `api/python/yr` 原语

传统 actor API 继续提供 checkpoint catalog；它与 Sandbox SDK 的 tenant reusable catalog 不是
同一个 Python 对象模型：

```python
import yr

yr.init()

@yr.instance
class Counter:
    def __init__(self):
        self.value = 0

    def increment(self):
        self.value += 1
        return self.value

counter = Counter.invoke()
yr.get(counter.increment.invoke())

checkpoint_id = counter.snapshot(ttl=600, leave_running=False)
restored = Counter.snapstart(checkpoint_id)
# 等价入口：yr.restore_from_checkpoint(checkpoint_id, Counter)

print(Counter.list_checkpoints())
print(yr.list_checkpoints(Counter))
yr.delete_checkpoint(checkpoint_id)
yr.finalize()
```

`InstanceProxy.snapshot(ttl=-1, leave_running=False)` 走 signal 18；`snapstart()` 走 signal 19 并
返回新的 `InstanceProxy`。`leave_running=False` 会把原 handle 标为不活跃。底层
`Runtime.reload_instance(instance_id) -> bool` 是 cluster runtime 原语，当前没有作为顶层
`yr.reload_instance` 导出；Sandbox 用户应使用 `Sandbox.reload()`。

内部 `SnapType` 值为 `DUMPSTATE=0`、`SNAPSHOT=1`、`PAUSE_RESUME=2`。不要把 legacy
checkpoint ID、可复用 Snapshot ID 和 local recovery candidate ID 混用。

## 存储模式与部署配置

### Kubernetes / Helm

默认值位于 `deploy/k8s/charts/openyuanrong/values.yaml`：

```yaml
global:
  pauseResume:
    checkpointRoot: /home/sn/checkpoints
    snapshotStorage:
      mode: local_only
      backend: ""
      obs:
        endpoint: ""
        bucket: ""
        useHttps: true
        pathStyle: false
        credentials:
          secretName: ""
          accessKeyKey: accesskey
          secretKeyKey: secretkey
          securityTokenKey: securitytoken
      dataSystem:
        host: 127.0.0.1
        port: 31501
```

| mode | 本地目录 | 远端 backend | 放置与清理 |
|---|---|---|---|
| `local_only` | 权威 artifact，保留到生命周期清理 | 无 | Create/Resume required source node |
| `distributed_cache` | 有界 LRU cache | `datasystem` 或 `obs` | 可跨节点；restore pin 阻止驱逐 |
| `distributed_only` | 只在 capture/publication/materialize/pin 期间存在 | `datasystem` 或 `obs` | 发布或最后 unpin 后删除本地目录 |

Helm 把 checkpoint root 以同一个 `emptyDir` 挂载给 FunctionAgent 和 RuntimeManager，不挂载给
FunctionProxy。因此 pod 重建会丢失 local-only artifact 和 process-local candidate；`distributed_cache` 的本地
cache 也会丢失，但 READY 远端对象仍可重新 materialize。需要 OBS 时必须提供已有 Secret；AK、
SK 和 security token 只注入 FunctionAgent。需要 DataSystem 时确认服务地址、端口及能力实际
可用。

FunctionSystem 的 `snapshot_local_cache_max_bytes` 默认 `10 GiB`，只影响
`distributed_cache`，并且是软预算：新提交和已 pin 的 artifact 可暂时超过预算。当前根 Helm
schema 未单独暴露该字段，如需调整应通过受控的 FunctionAgent 参数扩展完成，避免创建第二套
同名配置。

### 进程模式与 yrcli

- `yrcli` 模板把 FunctionAgent 与 FunctionProxy 的 `snapshot_storage_mode` 显式设置为
  `local_only`，把 RuntimeManager/FunctionAgent 的 checkpoint 路径设置为
  `{deploy_path}/checkpoints`。
- `deploy/process/config.sh` 默认 `SNAPSHOT_STORAGE_MODE=local_only`、backend 和 checkpoint dir
  为空；`checkpoint_dir` 为空时 FunctionAgent snapshot data plane 不启用。非空路径必须为绝对
  路径。
- 进程模式 wrapper 接受 `local_only`、`distributed_cache`、`distributed_only`。后两种当前只
  接受 `--snapshot_storage_backend datasystem`；OBS 的加密凭据与 Secret 注入由 Helm 路径提供。

FunctionSystem 自身的 FunctionAgent flag 默认同样是 `local_only`、空 backend、空
`checkpoint_dir`；RuntimeManager 单独启动时的内部 checkpoint default 是
`/home/yuanrong/checkpoints`。集成部署必须覆盖为同一个目录，不能依赖两个不同默认值。

## Timeout、重试与结果未知

- raw HTTP Snapshot/Pause 的 `timeoutSeconds` 都默认 `300`、校验 `1..3600`、换算并转发为逻辑
  checkpoint/direct-proxy timeout；只有这两个 body 当前接收调用方 logical timeout。
- SDK Snapshot、Pause、Resume、Reload 的每次 HTTP attempt 默认等待 `300 + 30` 秒：`300` 秒逻辑
  timeout 加 `30` 秒传输缓冲。Snapshot/Pause 暴露 `timeout_seconds` 并写入 body；Resume/Reload
  只使用 SDK transport 默认值，当前没有独立 body timeout 参数。
- FunctionSystem 接受 `1..3,600,000` 毫秒并向上取整传给 sandboxd。没有上层配置的内部物理
  plan 默认 `180` 秒。
- 同一个 timeout 分别限制物理 checkpoint response 和 publication response wait；它不是贯穿
  capture、archive、gzip、DataSystem/OBS Put 的共享绝对 deadline，也不会取消已经开始的 Agent
  后台发布。
- Pause/Resume/Reload 的 SDK 最多执行三次上述 HTTP attempt，并在同一次方法调用内复用一个
  request ID。可复用 Snapshot 创建只执行一次 attempt；连接断开或 gateway error 会以包含
  request ID 的“结果未知”错误返回。
- Proxy 的 SnapshotRuntime 等待使用通用 `RequestSyncHelper`；同 request ID 的后一次 synchronizer
  会替换前一次，当前没有 multi-waiter coalescing 或独立 physical-attempt correlation。避免并发复用
  同一 business ID，结果未知时查询 catalog/InstanceInfo。
- 对结果未知的操作，只能以相同 request ID 重放或查询权威 catalog/InstanceInfo；生成新 ID 会
  创建另一个逻辑 attempt，不能用于确认前一次结果。

## 清理与保留

- 可复用 Snapshot 由 `Sandbox.delete_snapshot()` 显式删除；一次 Create 不消费它。
- Pause artifact 由 PAUSED 记录和 TTL 约束，Resume/Delete/finalize 负责本地与远端清理。
- local recovery candidate 由新的候选、实例删除或 recovery finalize 清理，始终留在本节点。
- `distributed_cache` 的 restore pin 结束前不会被 LRU 删除；`distributed_only` 在最后一个 pin
  释放后删除 materialized 目录。
- `PAUSE_ABORTED` 不删除可能已经发布成功但响应未知的 final object；部分 DataSystem/remote
  delete error 按 best effort 处理。因此远端 orphan 需要容量监控与离线回收，不能假设所有失败
  都会精确删除。
- 不要手工删除 PAUSED/READY catalog 仍引用的对象，也不要把 checkpoint root 中未知目录手工
  加入 Agent index。

## 可观测性与排障

建议按以下顺序检查：

1. Frontend HTTP status、`X-Request-Id`/`X-YR-Request-ID`、tenant header 和 decoded envelope。
2. FunctionMaster 的 reusable phase 或 PAUSED `InstanceInfo`、SnapshotInfo、version 与 winner。
3. FunctionProxy 的 lifecycle gate、source/target runtime、Resume CAS 或 local recovery context。
4. FunctionAgent 的 mode/backend、LocalSnapshotView、pin/LRU、publication/materialize 结果。
5. RuntimeManager 的 capability、sandboxd Start/List/Wait、runtime/container 与端口事实。
6. RRT 的 `PrepareSnap`、handoff、`SnapStarted`、checkpoint socket 和 listener rearm。

日志应关联 request ID、snapshot ID、instance ID、runtime ID、source/target node、backend 和 version。
Publisher 当前记录 `checkpoint.compress_ms`、`checkpoint.published_bytes`、
`checkpoint.remote_put_ms`、`checkpoint.total_ms` 与 direct-final 标志。监控 checkpoint root、LRU/pin、
DataSystem/OBS 容量和认证、PAUSED/PUBLISHING/DELETING 数量、CAS loser、ghost cleanup 和远端 orphan。

常见现象：

| 现象 | 优先检查 |
|---|---|
| `checkpoint/restore unsupported` | runtime capability 是否已初始化且为 true |
| local Snapshot 在目标节点找不到 | sourceNodeID required affinity 和源 pod/Agent 是否仍存在 |
| Failover/Reload 返回失败 | 是否存在 local recovery candidate、Agent 是否重启、source version/runtime 是否已变化 |
| Pause timeout 后对象仍出现 | result-unknown 窗口；按原 request ID 与 final Stat/catalog 收敛 |
| Resume 成功后首次请求失败 | ETCD watch/read-through、winner route 和后端 listener 是否已收敛 |
| cache 超预算 | 是否有新提交保护项或 restore pin；该值是软预算 |
| 可复用 Snapshot 被拒绝 | 是否存在活动 reverse-tunnel session 或同实例 lifecycle 操作 |

## 限制、安全与升级

- local artifact 和 local recovery candidate 不提供节点磁盘/pod 丢失后的恢复保证。
- Agent 本地 descriptor 不持久化；Agent 重启后 process-local candidate 不可发现。携带权威 ID 的 Pause/Reusable
  local restore 可验证安全非空目录并补建最小 pin record，但不能反推出完整 tenant/source/backend
  元数据。
- Snapshot metadata 当前不绑定 runtime class 或 architecture。RuntimeManager 只在目标侧通过
  runtime capability gate；运维必须保证源/目标镜像、内核和 runtime 的 checkpoint 兼容性。
- 不支持跨节点 local Failover/Reload，不支持缺候选时 cold-start fallback，不承诺连接透明续接。
- FunctionAgent 把 sandboxd 输出当 opaque 目录，只接受普通目录/文件，拒绝符号链接、device、
  socket、绝对路径和 `..`。分布式 archive 的相对路径上限为 4096 bytes。
- OBS 凭据必须以部署支持的密文/Secret 提供，避免出现在 values、命令历史和日志中。tenant hash
  只用于 object key 隔离，不能替代 IAM、bucket policy 和网络隔离。
- 升级顺序应为 sandboxd/RuntimeManager、FunctionAgent/Proxy/Master、Frontend/SDK。回滚前停止新
  lifecycle 请求并等待 publication、Resume attempt 和 restore pin 收敛；不要让旧组件重解释已有
  backend/sourceNodeID。

## 验证策略

上线前至少验证：

- SDK 参数、typed result、request ID 重用和 raw HTTP header/envelope 差异。
- 六种操作的权威状态和 artifact owner，而不是固定测试数量或历史耗时。
- 三种 storage mode、DataSystem/OBS、local required 与 distributed placement。
- checkpoint/publication response 丢失、迟到成功、Agent/RuntimeManager 重启、Resume 并发 winner/
  loser、LRU/pin 竞争和远端删除失败。
- RRT activity、Unix checkpoint endpoint、handoff、restore 后 identity rebind 与 `SnapStarted` listener
  rearm。
- checkpoint root 残留、远端对象数、端口映射与 RUNNING winner 一致性。

真实 sandboxd/Firecracker、大 artifact、远端 backend 故障和节点重启行为必须在目标部署环境中
验收；单元测试或文档检查不能替代这些集成证据。
