# Routing Optimization - LRU Direct Routing with Feature Flag

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留原有 etcd watch 广播机制的基础上，增加 `enable_direct_routing` 开关启用新路由优化路径：实例节点单点写入终态、notifyresult 直接返回路由、LRU 缓存+按需查询替代全量广播，两套机制并存可切换。

**Architecture:**

1. **functionsystem**：通过 `enable_direct_routing` 配置开关控制新路径。开关开启时：实例节点 function_proxy 通过 TXN CAS 写入终态（含 RUNNING）到 etcd；instance_proxy 引入 LRU cache，按路由规则 3.1-3.4 转发；ObserverActor 订阅节点异常事件（`/yr/abnormal/localscheduler/` 前缀）实现 LRU 批量淘汰。**注意**：原有全量 INSTANCE_ROUTE watch 注册在开关开启时禁用（全局广播替换）；但 per-instance 订阅 fallback（规则 3.3 的 `SubscribeInstanceEvent`）在两种模式下均保留，作为 LRU miss 后的兜底路径。
2. **yuanrong SDK**：开关开启时，缓存 notifyresult 返回的路由，invoke/kill 均携带路由。
3. **faas frontend**：开关开启时，scheduler 返回租约携带 functionProxyID，frontend invoke 通过 YR_ROUTE 传递。

**Tech Stack:** C++17 (functionsystem, LiteBus actor), Go (yuanrong SDK, faasscheduler, faas frontend), protobuf/gRPC, etcd TXN CAS.

---

## 节点故障处理方案（3.4 设计）

**核心认识**：litebus 的 `SendForwardCall` 是 actor 消息传递层，不直接感知底层网络层面的节点故障。故障检测依赖 etcd 异常状态订阅。

**方案：订阅节点异常事件，主动淘汰 LRU**

- 节点异常 etcd 路径：`/yr/abnormal/localscheduler/<nodeID>`（由 `function_master` 写入）
- `ObserverActor` **新增**对 `/yr/abnormal/localscheduler/` 前缀的 watch（借鉴 `instance_manager_actor.cpp:300` 的已有实现）
- 当远程节点 `X` 被标记为 abnormal，ObserverActor 通知 `InstanceView`
- `InstanceView` 维护 `nodeID → [instanceIDs]` 反向映射（从已有的 `InstanceRouterInfo.remote` 地址中提取 nodeID）
- 批量调用各 `InstanceProxy::EvictRoute(instanceID)` 淘汰受影响的 LRU 条目
- 被淘汰后，后续请求走规则 3.3（订阅 observer 查询最新路由）

**故障窗口**：从节点故障到 function_master 写入 abnormal key，存在短暂窗口（取决于心跳间隔）。此窗口内发出的携带缓存路由的请求可能失败，调用方应有幂等重试。

---

## 涉及文件结构

### functionsystem（C++）

| 操作 | 文件 | 变更内容 |
|------|------|---------|
| Merge | `functionsystem/src/common/lru/lru_cache.h` | 从 `robb/001-generic-lru-module` 分支引入 LRU 实现 |
| Merge | `functionsystem/src/common/lru/thread_safe_lru_cache.h` | 同上 |
| **Create** | `functionsystem/src/function_proxy/config/direct_routing_config.h` | `enable_direct_routing` 开关定义及读取 |
| Modify | `proto/posix/runtime_service.proto` | NotifyRequest 添加 `resources.InstanceInfo readyInstance` 字段（同节点路径） |
| Modify | `functionsystem/src/common/proto/pb/posix/runtime_service.pb.h/cc` | 重新生成 proto stubs |
| Modify | `functionsystem/src/function_proxy/common/observer/data_plane_observer/data_plane_observer.h` | 添加 `QueryInstanceRoute` 虚函数（淘汰路径不走接口，直接调用链） |
| Modify | `functionsystem/tests/unit/mocks/mock_data_observer.h` | 更新 mock 添加新方法 |
| Modify | `functionsystem/src/function_proxy/busproxy/instance_proxy/instance_proxy.h` | 添加 `routeCache_` LRU 成员（开关开启时激活） |
| Modify | `functionsystem/src/function_proxy/busproxy/instance_proxy/instance_proxy.cpp` | 实现 LRU 路由缓存逻辑（3.1-3.4），原 watch 路径保留 |
| Modify | `functionsystem/src/function_proxy/busproxy/instance_view/instance_view.h/cpp` | 维护 `proxyGrpcAddress` 在内存 `InstanceRouterInfo` 中供 `QueryInstanceRoute` 使用；维护 nodeID→instanceIDs 反向映射，节点故障时批量调用 `InstanceProxy::EvictRoute()` |
| Modify | `functionsystem/src/function_proxy/common/observer/observer_actor.h/cpp` | 添加 `QueryInstanceRoute` 按需查询；新增 `/yr/abnormal/localscheduler/` 前缀 watch；开关开启时禁用 INSTANCE_ROUTE watch（保留代码） |
| Read/Verify | `functionsystem/src/function_proxy/local_scheduler/instance_control/` | 验证现有 InstanceOperator CAS 已覆盖路由写入；确认错误传播路径 |
| Test | `functionsystem/tests/unit/function_proxy/busproxy/instance_proxy/instance_proxy_test.cpp` | 添加 LRU cache 路由规则测试 |

### yuanrong SDK / faasscheduler（Go）

| 操作 | 文件 | 变更内容 |
|------|------|---------|
| Modify | `api/go/faassdk/runtime.go` | CreateInstance 后缓存路由；invoke 时加 YR_ROUTE；Kill 接受路由参数 |
| Modify | `api/go/libruntime/api/api.go` | Kill 签名加 `invokeOpt InvokeOptions` 参数 |
| Modify | `api/go/libruntime/api/types.go` | InstanceAllocation 添加 `RouteAddress string` |
| Modify | `go/pkg/functionscaler/instance_operation_kernel.go` | kill 时传路由；缓存 notifyresult 路由 |
| Modify | `go/pkg/common/faas_common/types/lease.go` | InstanceAllocationInfo 添加 `FunctionProxyID string`（路由地址）|
| Test | `api/go/faassdk/runtime_test.go` | 添加路由缓存和传递测试 |

### faas frontend（Go）

| 操作 | 文件 | 变更内容 |
|------|------|---------|
| Modify | `pkg/frontend/common/util/client.go` | InvokeRequest 添加 `RouteAddress string` |
| Modify | `pkg/frontend/invocation/function_invoke_for_kernel.go` | convert() 从租约提取路由，写入 CreateOpt["YR_ROUTE"] |
| Modify | `pkg/frontend/leaseadaptor/lease_manager.go` | 返回 InstanceAllocationInfo 时保留 FunctionProxyID |
| Modify | `go/pkg/functionscaler/faasscheduler.go` | generateInstanceResponse 填充 FunctionProxyID（来自 notifyresult）|
| Test | `pkg/frontend/invocation/function_invoke_for_kernel_test.go` | 验证路由从租约传递到 invoke |

---

## Phase 0：functionsystem - Feature Flag 开关

### Task 0：添加 `enable_direct_routing` 配置开关

**Files:**

- Create: `functionsystem/src/function_proxy/config/direct_routing_config.h`
- Modify: 相关初始化配置文件（参考现有 config 目录的加载方式）

- [ ] **Step 1: 查看现有配置加载方式**

```bash
find /Users/robbluo/code/yuanrong-functionsystem/functionsystem/src/function_proxy -name "*.h" | xargs grep -l "config\|Config" | head -5
# 找到现有配置类，复用其加载模式（JSON config, env var, 或 CLI flag）

```

- [ ] **Step 2: 创建开关定义**

新建 `functionsystem/src/function_proxy/config/direct_routing_config.h`：

```cpp
#pragma once
#include <atomic>

namespace functionsystem::function_proxy {

// Feature flag: enable direct routing via LRU cache and single-writer persistence.
// When false (default), the original etcd watch-based broadcast path is used.
// When true, the new direct routing path is activated.
class DirectRoutingConfig {
public:
    static bool IsEnabled() { return enabled_.load(std::memory_order_relaxed); }
    static void SetEnabled(bool enabled) { enabled_.store(enabled, std::memory_order_relaxed); }

private:
    inline static std::atomic<bool> enabled_{ false };
};

}  // namespace functionsystem::function_proxy

```

- [ ] **Step 3: 在启动配置解析时读取开关**

在 function_proxy 初始化代码（找 `FunctionProxyDriver` 或 `BusProxyDriver` 的启动入口）中读取配置：

```cpp
// Read enable_direct_routing from config (JSON key or env var)
bool enableDirectRouting = config.GetBool("enable_direct_routing", false);
DirectRoutingConfig::SetEnabled(enableDirectRouting);
YRLOG_INFO("DirectRouting feature flag: {}", enableDirectRouting);

```

- [ ] **Step 4: 编译验证**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh build -j 4"

```

- [ ] **Step 5: Commit**

```bash
git add functionsystem/src/function_proxy/config/
git commit --signoff -m "feat(config): add enable_direct_routing feature flag for routing optimization"

```

---

## Phase 1：functionsystem - 引入 LRU 缓存模块

### Task 1：从特性分支合并 LRU 实现

**Files:**

- Create: `functionsystem/src/common/lru/lru_cache.h`
- Create: `functionsystem/src/common/lru/thread_safe_lru_cache.h`
- Modify: `functionsystem/src/common/CMakeLists.txt`

- [ ] **Step 1: Cherry-pick LRU commit**

```bash
cd /Users/robbluo/code/yuanrong-functionsystem
git log remotes/robb/001-generic-lru-module --oneline | head -5
# 找到 LRU 相关 commit hash（通常是最新的那个）
git cherry-pick <lru-commit-hash>

```

- [ ] **Step 2: 验证文件存在**

```bash
ls functionsystem/src/common/lru/
# 预期：lru_cache.h  thread_safe_lru_cache.h  CMakeLists.txt

```

- [ ] **Step 3: 运行 LRU 单元测试**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -s LruCacheTest"

```

预期：所有 LRU 测试通过（约 20 个测试用例）

- [ ] **Step 4: Commit**

```bash
git add functionsystem/src/common/lru/ functionsystem/src/common/CMakeLists.txt
git commit --signoff -m "feat(common): merge LRU cache module from feature branch"

```

---

## Phase 2：functionsystem - proto 路由传播

> **不修改 `inner_service::NotifyRequest`**（Codex review 指出该 proto 是跨 proxy 通知，非 SDK 回调路径）。
> 正确路径：跨节点复用已有 `ForwardCallResultRequest.readyInstance`；同节点修改 `runtime_service::NotifyRequest`。

### Task 2：通过 readyInstance 传播路由信息

**Files:**

- Modify: `proto/posix/runtime_service.proto`（同节点本地路径）
- Modify: `functionsystem/src/common/proto/pb/posix/runtime_service.pb.h/cc` (generated)
- Modify: `functionsystem/src/function_proxy/local_scheduler/instance_control/instance_ctrl_actor.cpp`（填充 readyInstance）
- Sync check: `yuanrong/go/proto/posix/runtime_service.proto`（如存在需同步）

- [ ] **Step 1: 确认跨节点路径已覆盖路由**

```bash
grep -n "readyinstance\|readyInstance\|mutable_readyinstance" \
  /Users/robbluo/code/yuanrong-functionsystem/functionsystem/src/function_proxy/local_scheduler/instance_control/instance_ctrl_actor.cpp | head -10

```

预期：第 2665 行附近已有 `forwardCallResultRequest->mutable_readyinstance()->CopyFrom(...)` ✓ 无需改动

- [ ] **Step 2: 修改 runtime_service.proto（同节点路径）**

在 `proto/posix/runtime_service.proto` 的 `NotifyRequest` 末尾添加 `readyInstance` 字段：

```protobuf
// Add after existing fields (check current max field number first)
resources.InstanceInfo readyInstance = 8;  // Route info for local create path

```

- [ ] **Step 3: 在 SendNotifyResult() 中填充 readyInstance**

`SendNotifyResult()` 位于 `instance_ctrl_actor.cpp` 第 2729-2765 行，在构建 `runtime_service::NotifyRequest` 时填充：

```cpp
// Populate route info for local notify path (mirrors ForwardCallResultRequest.readyInstance).
// Called from ExecuteStateChangeCallback chain after RUNNING state is confirmed.
if (DirectRoutingConfig::IsEnabled() &&
    callResult && callResult->has_instanceinfo() &&
    !callResult->instanceinfo().proxygRPCaddress().empty()) {
    notifyReq.mutable_readyinstance()->CopyFrom(callResult->instanceinfo());
}

```

> **时序说明**：`InstanceOperator::Create()` 在 `TransitionTo()` 内部执行，`SendNotifyResult` 在 `TransInstanceState()` 的 `.Then()` 回调中调用（即 `Create()` 完成后）。因此 SDK 收到 `readyInstance` 时，etcd CAS 写入已完成。时序正确，无需额外调整。

- [ ] **Step 4: 在 function_proxy create 响应中提取 proxyGrpcAddress 返回给 SDK**

在处理 create 请求完成的回调处，提取 `proxyGrpcAddress`（`ip:port` 格式）并通过 litebus call response 返回：

```cpp
// Extract route address from readyInstance (ip:port, used as YR_ROUTE value)
if (result.has_readyinstance() && !result.readyinstance().proxygRPCaddress().empty()) {
    responseRouteAddress = result.readyinstance().proxygRPCaddress();
}

```

- [ ] **Step 5: 重新生成 runtime_service proto stubs（手动）**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-functionsystem && \
  protoc --cpp_out=functionsystem/src/common/proto/pb/posix \
         --grpc_out=functionsystem/src/common/proto/pb/posix \
         --plugin=protoc-gen-grpc=$(which grpc_cpp_plugin) \
         -I proto/posix -I vendor/src/protobuf/include \
         proto/posix/runtime_service.proto"

```

- [ ] **Step 5a: 清点所有镜像副本（search-driven，不硬编码路径）**

```bash
# Find ALL runtime_service.proto copies across all repos
find /Users/robbluo/code/yuanrong /Users/robbluo/code/yuanrong-functionsystem \
  -name "runtime_service.proto" 2>/dev/null

```

对每个找到的副本，手动同步 `NotifyRequest` 的 `readyInstance` 字段添加（保持 field number 一致）。已知可能包含：

- `yuanrong/go/proto/posix/runtime_service.proto`
- `yuanrong/go/pkg/common/protobuf/rpc/runtime_service.proto`
- `yuanrong/src/libruntime/fsclient/protobuf/runtime_service.proto`
- 以及 find 命令发现的任何其他副本

- [ ] **Step 6: 编译验证**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh build -j 4"

```

- [ ] **Step 7: Commit**

```bash
git add proto/posix/runtime_service.proto functionsystem/src/common/proto/pb/posix/runtime_service.pb.*
git commit --signoff -m "feat(proto): add readyInstance to runtime NotifyRequest for local routing propagation"

```

---

## Phase 3：functionsystem - InstanceView 维护路由数据供按需查询

> **不修改 `inner_service::NotifyRequest`**。路由信息通过两条路径传播：
>
> - **跨节点**：已有 `ForwardCallResultRequest.readyInstance.proxyGrpcAddress`（Phase 2 确认，无需改动）
> - **同节点**：新增 `runtime_service::NotifyRequest.readyInstance.proxyGrpcAddress`（Phase 2 完成）
>
> 本阶段目标：确保 `InstanceView` 在内存中维护 `instanceID → proxyGrpcAddress (ip:port)` 映射，
> 使 Task 6 的 `ObserverActor::QueryInstanceRoute()` 可从内存直接返回路由，不走 etcd。

### Task 3：InstanceView 维护 proxyGrpcAddress 供 QueryInstanceRoute 使用

**Files:**

- Modify: `functionsystem/src/function_proxy/busproxy/instance_view/instance_view.cpp`
- Modify: `functionsystem/src/function_proxy/busproxy/instance_view/instance_view.h`

- [ ] **Step 1: 阅读 InstanceRouterInfo 结构和更新流程**

```bash
grep -n "InstanceRouterInfo\|NotifyChanged\|proxyGrpc\|proxyGrpcAddress\|readyinstance" \
  functionsystem/src/function_proxy/busproxy/instance_view/instance_view.cpp | head -30
grep -n "InstanceRouterInfo" \
  functionsystem/src/function_proxy/busproxy/request_dispatcher/request_dispatcher.h | head -20

```

确认 `InstanceRouterInfo` 是否已有 `proxyGrpcAddress` 字段（`ip:port` 格式）；若无，查看 `InstanceInfo` proto 的 `proxyGrpcAddress` 字段如何在 `NotifyChanged` 时更新到内存。

- [ ] **Step 2: 确保 InstanceRouterInfo 存储 proxyGrpcAddress (ip:port)**

在 `NotifyChanged`（或等效函数）中，从 `InstanceInfo` 提取 `proxyGrpcAddress`（`ip:port` 格式）并存入 `InstanceRouterInfo`：

```cpp
// Store route address in ip:port format (used by QueryInstanceRoute)
if (!instanceInfo.proxygRPCaddress().empty()) {
    routerInfo.proxyGrpcAddress = instanceInfo.proxygRPCaddress();
}

```

- [ ] **Step 3: 验证 GetInstanceRouterInfo 可返回 proxyGrpcAddress**

```bash
grep -n "GetInstanceRouterInfo\|GetRouterInfo\|proxyGrpcAddress" \
  functionsystem/src/function_proxy/busproxy/instance_view/instance_view.h | head -10

```

确认 `ObserverActor` 可通过已有接口拿到 `routerInfo.proxyGrpcAddress`，无需额外变更。

- [ ] **Step 4: 编译验证**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh build -j 4"

```

- [ ] **Step 5: Commit**

```bash
git add functionsystem/src/function_proxy/busproxy/instance_view/
git commit --signoff -m "feat(instance_view): ensure proxyGrpcAddress stored in InstanceRouterInfo for on-demand query"

```

---

## Phase 4：functionsystem - 确认状态机 CAS 覆盖范围（无需新增写入逻辑）

> **关键发现**：`InstanceOperator` + `InstanceStateMachine` 已提供完整的 CAS 写入机制。**不需要新增任何 etcd 写入代码。**
>
> 已有的保证（通过代码阅读确认）：
>
> - **单点写入**：`instance_state_machine.cpp:273` — `instanceInfo.functionproxyid() == owner_` 守卫，只有本节点才写/删
> - **首写 CAS**：`InstanceOperator::Create()` 使用 `TxnCompare::OfVersion(key, EQUAL, 0)`，防止重复创建（RUNNING 状态首次写入）
> - **终态 CAS**：`InstanceOperator::Modify()` 使用版本乐观锁，防止乱序写入
> - **原子写入**：`GetPersistenceType()` 对 RUNNING 状态返回 `PERSISTENT_ALL`，`instance + routeInfo` 在同一个 TXN 中原子写入
>
> **`enable_direct_routing` 开关只影响 READ 侧**（LRU 缓存 + 禁用全量 watch），不影响 WRITE 侧。

### Task 4：验证路由写入内容，确认 proxyGrpcAddress 已包含在 routeInfo 中

**Files:**

- Read: `functionsystem/src/common/metadata/metadata.cpp`（`TransToRouteInfoFromInstanceInfo`）
- Read: `functionsystem/src/function_proxy/common/state_machine/instance_state_machine.cpp`（`TransRouteInfo`、`PersistToMetaStore`）
- 若缺失：Modify `metadata.cpp` 添加 `proxyGrpcAddress` 字段

- [ ] **Step 1: 确认 routeInfo 写入的字段**

```bash
grep -n "TransToRouteInfoFromInstanceInfo\|TransRouteInfo\|set_functionproxyid\|set_proxygRPCaddress\|proxyGrpcAddress" \
  functionsystem/src/common/metadata/metadata.cpp \
  functionsystem/src/function_proxy/common/state_machine/instance_state_machine.cpp

```

当前实现（已确认）：

```cpp
// metadata.cpp:109
void TransToRouteInfoFromInstanceInfo(const InstanceInfo &instanceInfo, resources::RouteInfo &routeInfo) {
    routeInfo.set_instanceid(instanceInfo.instanceid());
    routeInfo.set_functionproxyid(instanceInfo.functionproxyid());  // node ID, NOT ip:port
    routeInfo.set_runtimeaddress(instanceInfo.runtimeaddress());
    routeInfo.set_functionagentid(instanceInfo.functionagentid());
    // ...
}

```

- [ ] **Step 2: 检查 RouteInfo proto 是否有 proxyGrpcAddress 字段**

```bash
grep -n "proxyGrpcAddress\|proxygRPCaddress\|functionproxyid" \
  /Users/robbluo/code/yuanrong-functionsystem/proto/posix/resource.proto

```

**预期二选一**：

- A）`RouteInfo` 已有 `proxyGrpcAddress` 字段 → 只需在 `TransToRouteInfoFromInstanceInfo` 中填充
- B）`RouteInfo` 无此字段，仅有 `functionproxyid`（node ID）→ 需确认 `instance_proxy` 如何从 node ID 推导 litebus 地址

> **关键说明**：`instance_proxy.cpp` 中 `YR_ROUTE_KEY` 的值是 litebus address（`ip:port`），来自 create 响应中的 `proxyGrpcAddress`，**不是 etcd routeInfo 里的 `functionproxyid`（node ID）**。两者是不同的字段！
>
> - etcd routeInfo（`functionproxyid` = node ID）：用于原有 watch 路径下 ObserverActor 解析路由
> - LRU 缓存（`YR_ROUTE` = `proxyGrpcAddress` = `ip:port`）：用于直接路由路径，来自 create 响应（Phase 2）

- [ ] **Step 3: 根据 Step 2 结论决定是否修改 routeInfo**

> **主路由源**：LRU 直接路由的 `ip:port` 来自 Phase 2 的 create 响应（`readyInstance.proxyGrpcAddress`），经由 SDK → `YR_ROUTE` 选项传入 `instance_proxy`，缓存进 LRU。**etcd routeInfo 不是直接路由的数据源。**

**若 B**（只有 node ID，无 proxyGrpcAddress）：无需改动。Phase 4 验证完成，直接进入 Phase 5。etcd routeInfo 中的 `functionproxyid`（node ID）继续服务原有 watch 路径，与 LRU 路径无交集。

**若 A**（已有 proxyGrpcAddress 字段但未填充）：可选地在 `TransToRouteInfoFromInstanceInfo` 补充：

```cpp
routeInfo.set_proxygRPCaddress(instanceInfo.proxygRPCaddress());

```

**此变更是可选优化**，有助于 Phase 3 的内存 `InstanceRouterInfo.proxyGrpcAddress` 在 etcd 同步场景下有值可用，但不是 LRU 路由的关键路径。若此字段不存在于 proto 中，跳过此步骤。

- [ ] **Step 4: 确认 CAS 失败的错误传播路径**

```bash
grep -n "IsFirstPersistence\|OperateResult\|INSTANCE_TRANSACTION\|TransitionResult" \
  functionsystem/src/function_proxy/common/state_machine/instance_state_machine.cpp | head -20

```

确认 `InstanceOperator::Create()` 失败时（CAS 条件不满足），`OperateResult.status` 如何传播到 `TransInstanceState` 的调用方，调用方是否已经走 FATAL/FAILED 状态机路径。无需新增错误处理代码。

- [ ] **Step 5: 验证结论（无代码修改）**

本 Task 主要是验证和文档化。若 Step 3 需要补充字段，修改 `metadata.cpp` 中的 `TransToRouteInfoFromInstanceInfo`。

- [ ] **Step 6: Commit（仅在 Step 3 有修改时）**

```bash
git add functionsystem/src/common/metadata/metadata.cpp
git commit --signoff -m "feat(metadata): include proxyGrpcAddress in RouteInfo for direct routing path"

```

- [ ] **Step 5: 同样修改终态写入（FATAL/EXITED/EVICTED）**

终态写入使用 CAS 确保只从 RUNNING 状态转换。
> **注意**：终态 key 已存在（RUNNING 时写入），此处是 **UPDATE**（覆盖已有 key），不是首次创建。

**先运行验证命令（Step 5a），再写代码（Step 5b）**：

- [ ] **Step 5a: 确认 TxnOperation PUT/upsert API**

```bash
grep -n "static TxnOperation\|PutOption\|Create.*PutOption\|CreatePut\|Put(" \
  /Users/robbluo/code/yuanrong-functionsystem/functionsystem/src/meta_store/client/cpp/include/meta_store_client/txn_transaction.h

```

预期：找到 `TxnOperation::Create(key, value, PutOption)` 的静态工厂方法签名；当传入 `PutOption` 时为 PUT（upsert），而非 create-only 语义。
若存在 `TxnOperation::Put(...)` 或 `TxnOperation::CreatePut(...)` 专用 API，则优先使用该 API（语义更清晰）。

- [ ] **Step 5b: 终态 CAS 写入**

```cpp
// State transition: RUNNING → terminal (FATAL/EXITED/EVICTED)
// Condition: current state must be RUNNING (prevents double-transition)
txn.If(TxnCompare::OfValue(instanceStateKey,
                           TxnCompare::CompareOperator::EQUAL,
                           SerializeState(InstanceState::RUNNING)));

// PUT (overwrite) the existing state key with terminal value.
// IMPORTANT: Use whichever PUT API Step 5a confirmed:
//   Option A: TxnOperation::Put(key, value)  -- if this API exists
//   Option B: TxnOperation::Create(key, value, PutOption{.leaseID=0})  -- if Create+PutOption is the PUT form
// Do NOT blindly copy either form; verify the API signature first.
txn.Then(/* PUT_API_FROM_STEP_5A */ (instanceStateKey, SerializeState(newTerminalState)));

```

- [ ] **Step 6: 编译验证**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh build -j 4"

```

- [ ] **Step 7: Commit**

```bash
git add functionsystem/src/function_proxy/local_scheduler/instance_control/
git commit --signoff -m "feat(instance_control): use TXN CAS for route/state writes, rollback on conflict"

```

---

## Phase 5：functionsystem - LRU 路由缓存 + 移除全量 Watch

### Task 4.5（前置）：更新 DataPlaneObserver 抽象接口和 Mock

> **必须先完成此任务**，再修改 instance_proxy。InstanceProxy 通过 `DataPlaneObserver` 接口调用 observer，新方法需先在接口中声明。

**Files:**

- Modify: `functionsystem/src/function_proxy/common/observer/data_plane_observer/data_plane_observer.h`
- Modify: `functionsystem/src/function_proxy/common/observer/data_plane_observer/data_plane_observer.cpp`
- Modify: `functionsystem/tests/unit/mocks/mock_data_observer.h`（更新 mock）

- [ ] **Step 1: 阅读当前 DataPlaneObserver 接口**

```bash
cat /Users/robbluo/code/yuanrong-functionsystem/functionsystem/src/function_proxy/common/observer/data_plane_observer/data_plane_observer.h

```

- [ ] **Step 2: 只添加 QueryInstanceRoute 虚函数到接口**

> **LRU 淘汰路径（节点故障）不走此接口**：淘汰由 `ObserverActor` → `InstanceView` → `InstanceProxy::EvictRoute()` 直接调用链完成（见 Task 6 Step 5）。`DataPlaneObserver` 接口只需新增按需查询方法。

```cpp
// Query instance route on-demand (no watch). Used when LRU cache misses (rule 3.3/3.4).
virtual litebus::Future<std::shared_ptr<resources::RouteInfo>> QueryInstanceRoute(
    const std::string &instanceID);

```

- [ ] **Step 3: 实现 data_plane_observer.cpp 中的转发**

```cpp
litebus::Future<std::shared_ptr<resources::RouteInfo>>
DataPlaneObserver::QueryInstanceRoute(const std::string &instanceID)
{
    return litebus::Async(observerActor_->GetAID(),
                          &ObserverActor::QueryInstanceRoute, instanceID);
}

```

- [ ] **Step 4: 更新 mock_data_observer.h**

```cpp
MOCK_METHOD(litebus::Future<std::shared_ptr<resources::RouteInfo>>,
            QueryInstanceRoute, (const std::string &instanceID), (override));
// Note: EvictRoutesForNode is NOT on this interface; eviction uses direct call chain.

```

- [ ] **Step 5: 编译验证**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh build -j 4"

```

- [ ] **Step 6: Commit**

```bash
git add functionsystem/src/function_proxy/common/observer/data_plane_observer/ \
        functionsystem/tests/unit/mocks/mock_data_observer.h
git commit --signoff -m "feat(observer): add QueryInstanceRoute to DataPlaneObserver interface"

```

---

### Task 5：instance_proxy 添加 LRU 路由缓存

> **Feature flag 门控**：所有新路径（LRU 查缓存、ForwardWithRouteAndFallback）必须在 `DirectRoutingConfig::IsEnabled()` 为 true 时才激活。原有 `SubscribeInstanceEvent` 路径保留，作为 flag=false 时的 fallback。

**Observer 订阅点清单（均需 flag 门控）**：

1. `instance_proxy.cpp:91` — `Call()` cache miss 时的订阅
2. `instance_proxy.cpp:155` — `DoForwardCall()` 中的订阅
3. `instance_proxy.cpp:236` — `CallResult()` 中的订阅
4. `request_dispatcher.cpp:469` — `ReportTraffic()` （此调用无需 flag，保留原有行为）

**Files:**

- Modify: `functionsystem/src/function_proxy/busproxy/instance_proxy/instance_proxy.h`
- Modify: `functionsystem/src/function_proxy/busproxy/instance_proxy/instance_proxy.cpp`

- [ ] **Step 1: 先阅读 instance_proxy.h 全文**

```bash
cat functionsystem/src/function_proxy/busproxy/instance_proxy/instance_proxy.h

```

- [ ] **Step 2: 写失败测试（LRU 缓存命中场景）**

在 `instance_proxy_test.cpp` 添加：

```cpp
TEST_F(InstanceProxyTest, RouteFromLRUCacheWhenNoRouteInRequest) {
    // Setup: pre-populate LRU cache with a route for dstInstanceID
    // Action: Call() with request that has no YR_ROUTE in createoptions
    // Verify: forward is made to the cached route address (not observer subscribe)
    // ...
}

TEST_F(InstanceProxyTest, UpdateLRUCacheWhenRouteInRequest) {
    // Setup: LRU cache is empty
    // Action: Call() with YR_ROUTE in createoptions
    // Verify: route is cached in LRU after the call
}

TEST_F(InstanceProxyTest, FallbackToObserverWhenLRUCacheMiss) {
    // Setup: LRU cache is empty, no route in request
    // Action: Call()
    // Verify: SubscribeInstanceEvent is called on observer
}

```

- [ ] **Step 3: 运行测试确认失败**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -s InstanceProxyTest"

```

预期：新测试 FAIL（功能尚未实现）

- [ ] **Step 4: 在 instance_proxy.h 添加 LRU cache 成员**

```cpp
#include "common/lru/thread_safe_lru_cache.h"

class InstanceProxy : public ActorBase {
    // ...
private:
    // Route LRU cache: instanceID -> route address (litebus AID address component)
    // Capacity: 1024 entries, eviction callback removes stale remote dispatchers
    static constexpr size_t ROUTE_CACHE_CAPACITY = 1024;
    ThreadSafeLruCache<std::string, std::string> routeCache_{ROUTE_CACHE_CAPACITY};
};

```

- [ ] **Step 5: 修改 Call() 方法实现 3.1-3.3 路由规则**

在 `instance_proxy.cpp` 的 `Call()` 方法中，按如下逻辑修改（参考当前代码结构）：

**规则 3.1**：请求携带路由 → 更新 LRU + 直接转发（扩展现有逻辑）

```cpp
if (const auto it = callReq.createoptions().find(YR_ROUTE_KEY);
    it != callReq.createoptions().end() && !it->second.empty()) {
    // 3.1: Update LRU cache with the provided route
    routeCache_.Put(dstInstanceID, it->second);
    auto remoteAID = litebus::AID(dstInstanceID, it->second);
    // ... existing forward logic ...
}

```

**规则 3.2**（仅 flag=true 时走新路径）：无路由 + LRU 命中 → 用缓存路由直接转发

```cpp
// 3.2: Check LRU cache (only when direct routing is enabled)
if (DirectRoutingConfig::IsEnabled()) {
    if (auto cachedRoute = routeCache_.Get(dstInstanceID); cachedRoute.has_value()) {
        auto remoteAID = litebus::AID(dstInstanceID, *cachedRoute);
        return ForwardWithRouteAndFallback(remoteAID, dstInstanceID, callerInfo, request);
    }
}

```

**规则 3.3**：无路由 + LRU miss → subscribe observer（flag=false 时的原有行为保留）

```cpp
// 3.3: No cache entry, subscribe to observer for route resolution
// This is the original path, kept for both flag=false and flag=true LRU miss cases
if (remoteDispatchers_.find(dstInstanceID) == remoteDispatchers_.end()) {
    // ... existing subscribe logic (unchanged) ...
}

```

同样，`DoForwardCall()` (line 155) 和 `CallResult()` (line 236) 中的订阅点保持原逻辑不变，新路径只在 `Call()` 方法中通过 LRU cache 提前短路。

- [ ] **Step 6: 实现 3.4 - 节点故障回退逻辑**

新增 `ForwardWithRouteAndFallback` 方法：

```cpp
litebus::Future<SharedStreamMsg> InstanceProxy::ForwardWithRouteAndFallback(
    const litebus::AID &remoteAID,
    const std::string &dstInstanceID,
    const CallerInfo &callerInfo,
    const SharedStreamMsg &request)
{
    auto promise = std::make_shared<litebus::Promise<SharedStreamMsg>>();
    SendForwardCall(remoteAID, callerInfo.tenantID, request)
        .OnComplete(litebus::Defer(GetAID(),
            &InstanceProxy::OnForwardResult,
            dstInstanceID, request, promise, std::placeholders::_1));
    return promise->GetFuture();
}

void InstanceProxy::OnForwardResult(
    const std::string &dstInstanceID,
    const SharedStreamMsg &request,
    std::shared_ptr<litebus::Promise<SharedStreamMsg>> promise,
    const litebus::Future<SharedStreamMsg> &future)
{
    if (!future.IsError()) {
        auto rsp = future.Get();
        rsp->set_messageid(request->messageid());
        promise->SetValue(rsp);
        return;
    }
    // 3.4: Forward failed — evict stale route and query observer
    YRLOG_WARN("{}|Forward to cached route failed for instance {}, evicting and querying observer",
               request->callreq().traceid(), dstInstanceID);
    routeCache_.Remove(dstInstanceID);

    // Query observer for fresh route (one-time query, not subscribe)
    observer_->QueryInstanceRoute(dstInstanceID)
        .Then(litebus::Defer(GetAID(),
              &InstanceProxy::OnQueryRouteResult,
              dstInstanceID, request, promise, std::placeholders::_1));
}

```

- [ ] **Step 7: 运行测试确认通过**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -s InstanceProxyTest"

```

预期：所有 InstanceProxyTest 通过

- [ ] **Step 8: Commit**

```bash
git add functionsystem/src/function_proxy/busproxy/instance_proxy/
git commit --signoff -m "feat(instance_proxy): add LRU route cache with 3.1-3.4 routing rules"

```

### Task 6：ObserverActor 按需查询 + 节点异常订阅（3.4 故障检测）

**Files:**

- Modify: `functionsystem/src/function_proxy/common/observer/observer_actor.h`
- Modify: `functionsystem/src/function_proxy/common/observer/observer_actor.cpp`
- Modify: `functionsystem/src/function_proxy/busproxy/instance_view/instance_view.h/cpp`

- [ ] **Step 1: 阅读当前 ObserverActor Watch 注册代码**

```bash
grep -n "INSTANCE_ROUTE_PATH_PREFIX\|RegisterObserver\|UpdateInstanceRouteEvent\|ABNORMAL" \
  functionsystem/src/function_proxy/common/observer/observer_actor.cpp | head -20

```

- [ ] **Step 2: 添加 QueryInstanceRoute 方法（按需 GET，非 watch）**

在 `observer_actor.h` 添加接口：

```cpp
// Query instance route on-demand from metastore (no watch).
// Returns RouteInfo if found, or error if not found/terminal.
litebus::Future<std::shared_ptr<resources::RouteInfo>> QueryInstanceRoute(
    const std::string &instanceID);

```

在 `observer_actor.cpp` 实现（从 `InstanceView` 内存查询，不走 etcd）：

```cpp
litebus::Future<std::shared_ptr<resources::RouteInfo>>
ObserverActor::QueryInstanceRoute(const std::string &instanceID)
{
    // Query from in-memory InstanceRouterInfo maintained by InstanceView (Phase 3).
    // Returns proxyGrpcAddress (ip:port) directly without etcd round-trip.
    auto routerInfo = instanceView_->GetInstanceRouterInfo(instanceID);
    if (!routerInfo || routerInfo->proxyGrpcAddress.empty()) {
        return litebus::MakeErrorFuture<std::shared_ptr<resources::RouteInfo>>(
            common::ErrorCode::ERR_NOT_FOUND, "instance route not found");
    }
    auto result = std::make_shared<resources::RouteInfo>();
    // Use proxyGrpcAddress (ip:port) — NOT functionproxyid which holds node ID.
    // Caller (InstanceProxy) reads result->proxygRPCaddress() as YR_ROUTE value.
    result->set_proxygRPCaddress(routerInfo->proxyGrpcAddress);
    return litebus::MakeReadyFuture(result);
}

```

- [ ] **Step 3: 订阅节点异常事件（3.4 故障检测核心）**

在 `observer_actor.h` 添加：

```cpp
// Callback for remote node abnormal events (for LRU eviction).
// Registered as subscriber via InstanceView.
using NodeAbnormalCallback = std::function<void(const std::string &nodeID)>;
void RegisterNodeAbnormalCallback(NodeAbnormalCallback cb);

```

在 `observer_actor.cpp` 中，新增 `/yr/abnormal/localscheduler/` 前缀 watch（在 `enable_direct_routing` 开启时注册）：

```cpp
// Subscribe to node abnormal events for proactive LRU route eviction.
// Key path: /yr/abnormal/localscheduler/<nodeID>
// Reference: instance_manager_actor.cpp:300 for the same watch pattern.
if (DirectRoutingConfig::IsEnabled()) {
    const std::string ABNORMAL_PREFIX = "/yr/abnormal/localscheduler/";
    metaStorageAccessor_->RegisterObserver(
        ABNORMAL_PREFIX, { .prefix = true },
        [aid(GetAID())](const std::vector<WatchEvent> &events, bool) {
            litebus::Async(aid, &ObserverActor::OnNodeAbnormalEvent, events);
            return true;
        },
        nullptr);
}

```

实现 `OnNodeAbnormalEvent`：

```cpp
void ObserverActor::OnNodeAbnormalEvent(const std::vector<WatchEvent> &events)
{
    for (const auto &event : events) {
        if (event.eventType != WatchEventType::PUT) {
            continue;
        }
        // Extract nodeID from key: /yr/abnormal/localscheduler/<nodeID>
        std::string nodeID = event.key.substr(ABNORMAL_PREFIX.size());
        YRLOG_WARN("Node {} marked abnormal, notifying callbacks for LRU eviction", nodeID);
        for (const auto &cb : nodeAbnormalCallbacks_) {
            cb(nodeID);
        }
    }
}

```

- [ ] **Step 4: 在开关开启时禁用 INSTANCE_ROUTE watch（不删除，用 if 包裹）**

在 `observer_actor.cpp` 的路由 watch 注册处，用开关控制：

```cpp
// Original route watch: kept for backward compatibility when direct routing is disabled.
if (!DirectRoutingConfig::IsEnabled()) {
    RegisterObserver(INSTANCE_ROUTE_PATH_PREFIX, watchOpt,
        [aid(GetAID())](const std::vector<WatchEvent> &events, bool synced) {
            litebus::Async(aid, &ObserverActor::UpdateInstanceRouteEvent, events, synced);
            return true;
        },
        instanceInfoSyncer);
}

```

- [ ] **Step 5: InstanceView 注册 NodeAbnormal 回调，维护 nodeID→instanceIDs 映射**

> **淘汰路径**：`ObserverActor::OnNodeAbnormalEvent` → 回调 → `InstanceView::OnNodeAbnormal` → `InstanceProxy::EvictRoute(instanceID)`（直接调用链，不走 `DataPlaneObserver` 接口）。

在 `instance_view.h` 添加：

```cpp
// Maintain nodeID -> [instanceIDs] reverse mapping for batch LRU eviction.
// nodeID extracted from proxyGrpcAddress host part (ip:port -> ip).
std::unordered_map<std::string, std::unordered_set<std::string>> nodeInstanceMap_;

void OnNodeAbnormal(const std::string &nodeID);

```

在 `instance_view.cpp` 实现：

- 当 `NotifyChanged` 更新 `InstanceRouterInfo` 时，从 `routerInfo.proxyGrpcAddress`（`ip:port` 格式）中提取 host 部分作为 nodeID，更新 `nodeInstanceMap_`
- `OnNodeAbnormal(nodeID)` 时，遍历 `nodeInstanceMap_[nodeID]` 中所有 instanceIDs，调用各 `InstanceProxy::EvictRoute(instanceID)`（`InstanceProxy` 直接暴露 `EvictRoute` 方法，不通过 `DataPlaneObserver`）

- [ ] **Step 6: 编译验证**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh build -j 4"

```

- [ ] **Step 5: 运行全量测试**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4"

```

预期：所有原有测试通过，无回归

- [ ] **Step 6: Commit**

```bash
git add functionsystem/src/function_proxy/common/observer/
git commit --signoff -m "feat(observer): add QueryInstanceRoute on-demand query, remove route watch"

```

---

## Phase 6：yuanrong SDK - 路由缓存和传递

### Task 7：faassdk 缓存路由，invoke 携带 YR_ROUTE

**Files:**

- Modify: `/Users/robbluo/code/yuanrong/api/go/faassdk/runtime.go`
- Modify: `/Users/robbluo/code/yuanrong/api/go/libruntime/api/types.go`

- [ ] **Step 1: 阅读 faassdk/runtime.go 的 CreateInstance 和 Invoke 逻辑**

```bash
grep -n "CreateInstance\|GetAsync\|routeInfo\|YR_ROUTE" \
  /Users/robbluo/code/yuanrong/api/go/faassdk/runtime.go | head -30

```

- [ ] **Step 2: 在 InstanceAllocation 添加路由地址字段**

编辑 `api/go/libruntime/api/types.go`：

```go
type InstanceAllocation struct {
    FuncKey       string
    FuncSig       string
    InstanceID    string
    LeaseID       string
    LeaseInterval int64
    RouteAddress  string  // functionProxyID or litebus AID address for direct forwarding
}

```

- [ ] **Step 3: 在 runtime.go 添加路由缓存（map + mutex）**

```go
type SDK struct {
    // ... existing fields ...
    routeCache   map[string]string  // instanceID -> route address
    routeCacheMu sync.RWMutex
}

```

- [ ] **Step 4: CreateInstance 返回后缓存路由**

在 GetAsync 回调中，当实例创建成功时，从 allocation 的 RouteAddress 缓存：

```go
globalSdkClient.GetAsync(objID, func(result []byte, err error) {
    if err == nil {
        var alloc libruntime.InstanceAllocation
        json.Unmarshal(result, &alloc)
        if alloc.RouteAddress != "" {
            sdk.setRoute(alloc.InstanceID, alloc.RouteAddress)
        }
    }
    // ... existing logic ...
})

```

- [ ] **Step 5: Invoke 时从缓存取路由并写入 CreateOpt**

```go
func (s *SDK) invokeInstance(instanceID string, opts InvokeOptions) error {
    if route := s.getRoute(instanceID); route != "" {
        if opts.CreateOpt == nil {
            opts.CreateOpt = make(map[string]string)
        }
        opts.CreateOpt["YR_ROUTE"] = route
    }
    return s.globalSdkClient.Invoke(instanceID, opts)
}

```

- [ ] **Step 6: 编译验证**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong/api/go && go build ./..."

```

- [ ] **Step 7: Commit**

```bash
cd /Users/robbluo/code/yuanrong
git add api/go/faassdk/runtime.go api/go/libruntime/api/types.go
git commit --signoff -m "feat(faassdk): cache route from CreateInstance response, pass YR_ROUTE in invoke"

```

### Task 8：Kill 链路添加路由参数

> **Breaking Change 调用方清单**（修改签名前必须找到所有调用方并同步更新）：
>
> ```bash
> grep -rn "\.Kill(" /Users/robbluo/code/yuanrong/api/go \
>   /Users/robbluo/code/yuanrong/go \
>   /Users/robbluo/code/yuanrong-frontend/pkg --include="*.go" | grep -v "_test.go" | grep -v "mock"
> # 预期找到：api.go接口定义、clibruntime.go binding、faassdk wrapper、instance_operation_kernel.go
> # 如有 frontend 调用也需同步更新
> ```

**Files:**

- Modify: `/Users/robbluo/code/yuanrong/api/go/libruntime/api/api.go`
- Modify: `/Users/robbluo/code/yuanrong/api/go/faassdk/runtime.go`
- Modify: `/Users/robbluo/code/yuanrong/go/pkg/functionscaler/instance_operation_kernel.go`
- Update: All other callers found by the inventory grep above

- [ ] **Step 1: 先执行调用方清单搜索，列出所有需要更新的文件**

```bash
grep -rn "\.Kill(" /Users/robbluo/code/yuanrong/api/go \
  /Users/robbluo/code/yuanrong/go \
  /Users/robbluo/code/yuanrong-frontend/pkg --include="*.go" | grep -v "_test.go" | grep -v "mock"

```

- [ ] **Step 2: 修改 Kill 接口添加 InvokeOptions 参数**

编辑 `api/go/libruntime/api/api.go`：

```go
// Kill terminates an instance. Providing invokeOpt with YR_ROUTE enables direct routing.
Kill(instanceID string, signal int, payload []byte, invokeOpt InvokeOptions) error

```

- [ ] **Step 2: 更新 clibruntime.go 中 Kill 的 C binding**

参考 `cInvokeOptions()` 的实现模式，在 Kill 调用中传递 CreateOpt。

- [ ] **Step 3: 在 faassdk 的 Kill 包装器中注入路由**

```go
func (s *SDK) Kill(instanceID string, signal int, payload []byte) error {
    opts := InvokeOptions{}
    if route := s.getRoute(instanceID); route != "" {
        opts.CreateOpt = map[string]string{"YR_ROUTE": route}
    }
    err := s.globalSdkClient.Kill(instanceID, signal, payload, opts)
    if err == nil {
        // Instance killed successfully, remove from route cache
        s.removeRoute(instanceID)
    }
    return err
}

```

- [ ] **Step 4: instance_operation_kernel.go 更新调用签名**

```go
func killInstanceAndIgnoreNotFoundError(instanceId string) error {
    err := globalSdkClient.Kill(instanceId, killSignalVal, []byte{}, sdk.InvokeOptions{})
    // ...
}

```

- [ ] **Step 5: 编译验证**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong/go && bash build.sh"

```

- [ ] **Step 6: Commit**

```bash
cd /Users/robbluo/code/yuanrong
git add api/go/libruntime/api/api.go api/go/faassdk/runtime.go go/pkg/functionscaler/
git commit --signoff -m "feat(sdk): add route parameter to Kill path, clean route cache on kill"

```

---

## Phase 7：faasscheduler - notifyresult 路由 + 租约携带路由

### Task 9：scheduler 路由填入租约

> **关键发现（Codex review + 调查）**：`go/pkg/functionscaler/types/types.go` 中的 `InstanceSpecification` 已有 `FunctionProxyID string`，其值来自 `insSpec.FunctionProxyID = insSpecFG.InstanceIP + ":" + insSpecFG.InstancePort`（`ip:port` 格式）。这与 `YR_ROUTE` 的值格式完全一致。
>
> **因此：scheduler 可能无需等 notifyresult 路由返回，直接从 InstanceSpecification 读取 FunctionProxyID！**

**Files:**

- Modify: `/Users/robbluo/code/yuanrong/go/pkg/common/faas_common/types/lease.go`
- Modify: `/Users/robbluo/code/yuanrong/go/pkg/functionscaler/faasscheduler.go`

- [ ] **Step 1: 验证 InstanceSpecification.FunctionProxyID 已被填充**

```bash
grep -n "FunctionProxyID\|functionProxyID" \
  /Users/robbluo/code/yuanrong/go/pkg/functionscaler/types/types.go \
  /Users/robbluo/code/yuanrong/go/pkg/functionscaler/instancepool/instancepool.go | head -20
# 期望：FunctionProxyID 已在 Instance 对象中，从 etcd/registry 读取后填充

```

- [ ] **Step 2: 确认 InstanceAllocation.Instance.FunctionProxyID 在创建后可用**

```bash
grep -n "FunctionProxyID\|functionProxyID" \
  /Users/robbluo/code/yuanrong/go/pkg/functionscaler/instancepool/*.go | head -20
# 如果 CreateInstance 后返回的 Instance 对象已有 FunctionProxyID（从 registry 读取），
# 则跳过 notifyresult 路由解析步骤，直接使用

```

- [ ] **Step 3: 在 InstanceAllocationInfo 添加 FunctionProxyID 字段**

编辑 `go/pkg/common/faas_common/types/lease.go`：

```go
type InstanceAllocationInfo struct {
    FuncKey          string `json:"funcKey"`
    FuncSig          string `json:"funcSig"`
    InstanceID       string `json:"instanceID"`
    ThreadID         string `json:"threadID"`
    InstanceIP       string `json:"instanceIP"`
    InstancePort     string `json:"instancePort"`
    NodeIP           string `json:"nodeIP"`
    NodePort         string `json:"nodePort"`
    FunctionProxyID  string `json:"functionProxyID"`  // ip:port, used as YR_ROUTE value
    LeaseInterval    int64  `json:"leaseInterval"`
    CPU              int64  `json:"cpu"`
    Memory           int64  `json:"memory"`
    ForceInvoke      bool   `json:"forceInvoke"`
}

```

- [ ] **Step 4: generateInstanceResponse 填充 FunctionProxyID**

优先从 `Instance.FunctionProxyID`（已有）填充，无需依赖 notifyresult：

```go
func generateInstanceResponse(...) *commonTypes.InstanceResponse {
    return &commonTypes.InstanceResponse{
        InstanceAllocationInfo: commonTypes.InstanceAllocationInfo{
            // ... existing fields ...
            // FunctionProxyID: ip:port of the proxy where instance runs (YR_ROUTE value)
            // Source: Instance.FunctionProxyID (from InstanceSpecification, already populated)
            FunctionProxyID: insAlloc.Instance.FunctionProxyID,
        },
        // ...
    }
}

```

- [ ] **Step 5: 如果 FunctionProxyID 为空（未被填充），则从 notifyresult 路由补充**

这是 fallback 路径：

```go
// If FunctionProxyID not populated from InstanceSpecification,
// extract from notifyresult readyInstance.proxyGrpcAddress
if insAlloc.Instance.FunctionProxyID == "" && notifyResult != nil {
    insAlloc.Instance.FunctionProxyID = notifyResult.GetReadyInstance().GetProxyGrpcAddress()
}

```

- [ ] **Step 5: 编译验证**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong/go && bash build.sh"

```

- [ ] **Step 6: Commit**

```bash
cd /Users/robbluo/code/yuanrong
git add go/pkg/common/faas_common/types/lease.go go/pkg/functionscaler/
git commit --signoff -m "feat(faasscheduler): propagate FunctionProxyID from notifyresult to lease response"

```

---

## Phase 8：faas frontend - invoke 携带路由

### Task 10：frontend 从租约提取路由，写入 invoke CreateOpt

**Files:**

- Modify: `/Users/robbluo/code/yuanrong-frontend/pkg/frontend/common/util/client.go`
- Modify: `/Users/robbluo/code/yuanrong-frontend/pkg/frontend/invocation/function_invoke_for_kernel.go`

- [ ] **Step 1: InvokeRequest 添加 RouteAddress 字段**

编辑 `pkg/frontend/common/util/client.go`：

```go
type InvokeRequest struct {
    // ... existing fields ...
    RouteAddress string  // YR_ROUTE value for direct routing (functionProxyID)
}

```

- [ ] **Step 2: 写失败测试**

在 `pkg/frontend/invocation/function_invoke_for_kernel_test.go`：

```go
func TestConvert_PopulatesRouteFromLease(t *testing.T) {
    lease := &commontype.InstanceAllocationInfo{
        InstanceID:      "inst-001",
        FunctionProxyID: "10.0.0.1:5000",  // ip:port format (proxyGrpcAddress)
    }
    // ... create InvokeProcessContext with lease ...
    req, err := convert(ctx, funcSpec, lease.InstanceID, false, nil)
    assert.NoError(t, err)
    assert.Equal(t, "10.0.0.1:5000", req.RouteAddress)  // YR_ROUTE == ip:port
}

```

- [ ] **Step 3: 运行测试确认失败**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-frontend && go test ./pkg/frontend/invocation/..."

```

- [ ] **Step 4: 修改 convert() 从租约填充 RouteAddress**

在 `function_invoke_for_kernel.go` 的 `convert()` 函数中：

```go
func convert(ctx *types.InvokeProcessContext, funcSpec *commontype.FuncSpec,
    instanceId string, forceInvoke bool,
    legacySchedulerInfo *commontype.InstanceInfo) (*util.InvokeRequest, error) {

    req := &util.InvokeRequest{
        Function:    ctx.FuncKey,
        InstanceID:  instanceId,
        // ... existing fields ...
    }

    // Populate route from lease if available
    if lease := ctx.GetCurrentLease(); lease != nil && lease.FunctionProxyID != "" {
        req.RouteAddress = lease.FunctionProxyID
    }

    return req, nil
}

```

- [ ] **Step 5: 修改 NewClient().Invoke() 将 RouteAddress 写入 CreateOpt**

在 invoke 发起前，将路由写入 args 的 createopt：

```go
if request.RouteAddress != "" {
    // Add YR_ROUTE to the invoke args' create options
    invokeArgs = appendCreateOpt(invokeArgs, "YR_ROUTE", request.RouteAddress)
}

```

> **注意**：具体 arg 格式需参考 `util.NewClient().Invoke()` 的实现和 functionsystem 期望的 createopt 注入方式。

- [ ] **Step 6: 运行测试确认通过**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-frontend && go test ./pkg/frontend/invocation/..."

```

- [ ] **Step 7: 编译 frontend**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-frontend && bash build.sh"

```

- [ ] **Step 8: Commit**

```bash
cd /Users/robbluo/code/yuanrong-frontend
git add pkg/frontend/common/util/client.go pkg/frontend/invocation/
git commit --signoff -m "feat(frontend): pass FunctionProxyID as YR_ROUTE in invoke for direct routing"

```

---

## Phase 9：全量构建与集成验证

### Task 11：全量构建所有组件

- [ ] **Step 1: 编译 functionsystem**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh build -j 4 && bash run.sh pack"

```

- [ ] **Step 2: 运行 functionsystem 全量测试**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4"

```

- [ ] **Step 3: 编译 yuanrong faas 组件（Go）**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong/go && bash build.sh"

```

- [ ] **Step 4: 编译 frontend**

```bash
docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-frontend && bash build.sh"

```

- [ ] **Step 5: 部署验证（yr 环境）**

```bash
# 更新二进制
yr stop
# 替换 functionsystem, faasscheduler, faasfrontend
yr start

# 触发一个 FaaS 函数调用，观察日志
# 确认：1. 路由出现在 notifyresult 2. invoke 携带 YR_ROUTE 3. kill 携带路由

```

- [ ] **Step 6: 观察关键日志**

```bash
# 确认 LRU cache 命中日志出现
grep "YR_ROUTE\|LRU\|route cache\|CAS write" /path/to/function_proxy.log | head -20

# 确认不再有 INSTANCE_ROUTE watch 相关日志
grep "UpdateInstanceRouteEvent\|INSTANCE_ROUTE" /path/to/function_proxy.log | head -5
# 预期：无输出（watch 已移除）

```

---

## 关键风险与注意事项

1. **Proto 生成 stubs**：CLAUDE.md 明确指出 proto stubs **不在构建时自动生成**，需手动运行 protoc。务必更新 `.pb.h` 和 `.pb.cc` 文件并提交。

2. **LRU 容量调优**：初始值 1024 entries，每个条目约 100 bytes，总计约 100KB。根据集群实例密度调整。

3. **Kill 接口兼容性**：修改 `Kill()` 签名为 breaking change，需更新所有调用方。搜索全仓库：`globalSdkClient.Kill(` 确保全部更新。

4. **路由格式一致性**：`YR_ROUTE` 值必须是 litebus AID 的 address 部分（不含 instanceID）。确认 `FunctionProxyID` 的格式与 `litebus::AID(dstInstanceID, routeAddress)` 的 routeAddress 参数格式匹配。

5. **租约续期不携带路由**：`batchRetain` 响应中无路由信息，续期成功后应保留上次缓存的路由（不清除）。

6. **节点故障窗口**：从节点故障到 function_master 将实例标记为 FATAL，存在短暂窗口。此窗口内 observer 查询返回 RUNNING 但连接失败。当前方案：重试一次，失败后返回临时错误，调用方应有重试逻辑。
