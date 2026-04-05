# Direct Routing Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four gaps in the direct routing optimization: instance subscription filtering, single-write persistence at RUNNING, kill routing without state machine, and state machine GC for non-owner proxies.

**Architecture:** Each gap is an independent change in the C++ proxy (yuanrong-functionsystem) or Go faasscheduler/SDK (yuanrong). Proto changes in Task 1 are a prerequisite for Tasks 4–7. All other tasks are independent.

**Tech Stack:** C++17, protobuf3, Go 1.24, CGo, GoogleTest, litebus actor framework

---

## File Change Map

| File | Gap | Change |
|------|-----|--------|
| `go/proto/posix/common.proto` | Gap 3 | Add `proxyID = 4` to `RuntimeInfo` |
| `go/proto/posix/core_service.proto` | Gap 3 | Add `routeAddress = 5`, `proxyID = 6` to `KillRequest` |
| `functionsystem/src/function_proxy/common/observer/observer_actor.cpp` | Gap 1 | Replace unconditional `Sync` with local-filtered sync in DR mode |
| `functionsystem/src/function_proxy/common/state_machine/instance_state_machine.cpp` | Gap 2 | DR fast-path in `GetPersistenceType()` |
| `functionsystem/src/function_proxy/local_scheduler/instance_control/instance_ctrl_actor.cpp` | Gap 3, 4 | notifyresult proxyID; kill locality check; DeleteRequestFuture GC; runtimePromise timer |
| `go/pkg/common/faas_common/types/lease.go` | Gap 3 | Add `RouteAddress`, `ProxyID` to `InstanceAllocationInfo` |
| `go/pkg/functionscaler/faasscheduler.go` | Gap 3 | Populate in `generateInstanceResponse()` |
| `api/go/libruntime/cpplibruntime/clibruntime.h` | Gap 3 | Add `routeAddress`, `proxyID` to `CInstanceAllocation` and `CKill` |
| `api/go/libruntime/clibruntime/clibruntime.go` | Gap 3 | Read route from `CInstanceAllocation`; add route params to `Kill()` |
| `api/go/libruntime/libruntimesdkimpl/libruntimesdkimpl.go` | Gap 3 | Pass route params through `Kill()` |

### Test Files

| Test File | Tests For |
|-----------|-----------|
| `functionsystem/tests/unit/function_proxy/common/observer/control_plane_observer_test.cpp` | Gap 1 |
| `functionsystem/tests/unit/function_proxy/common/state_machine/state_machine_test.cpp` | Gap 2 |
| `functionsystem/tests/unit/function_proxy/local_scheduler/instance_control/instance_ctrl_actor_test.cpp` | Gap 3 (notifyresult), Gap 4 |
| `api/go/libruntime/clibruntime/clibruntime_test.go` | Gap 3 (Go path) |

---

## Task 1: Proto Field Additions

**Files:**
- Modify: `go/proto/posix/common.proto`
- Modify: `go/proto/posix/core_service.proto`

**Context:** These changes enable kill routing (Gap 3). `RuntimeInfo` in notifyresult carries the proxy's bus URL and ID to the SDK. `KillRequest` carries them back to the proxy for forwarding.

- [ ] **Step 1: Add `proxyID` to `RuntimeInfo` in common.proto**

```protobuf
// go/proto/posix/common.proto
message RuntimeInfo {
    string serverIpAddr = 1;
    int32  serverPort   = 2;
    string route        = 3;  // litebus bus URL of owner proxy
    string proxyID      = 4;  // functionProxyID of owner proxy (new)
}
```

- [ ] **Step 2: Add routing fields to `KillRequest` in core_service.proto**

```protobuf
// go/proto/posix/core_service.proto
message KillRequest {
    string instanceID    = 1;
    int32  signal        = 2;
    bytes  payload       = 3;
    string requestID     = 4;
    string routeAddress  = 5;  // litebus bus URL of owner proxy (new, used when DR enabled)
    string proxyID       = 6;  // functionProxyID of owner proxy (new, used when DR enabled)
}
```

- [ ] **Step 3: Regenerate proto bindings**

Run the project's proto generation command for both Go and C++ bindings. Verify that `common.pb.go`, `common.pb.h`, `core_service.pb.go`, `core_service.pb.h` all contain the new fields.

- [ ] **Step 4: Verify build compiles cleanly with new proto fields**

Run: `docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh build -j 4"`
Expected: Build succeeds (new fields are added, no existing code references them yet)

- [ ] **Step 5: Commit**

```bash
git add go/proto/posix/common.proto go/proto/posix/core_service.proto
# add regenerated pb files
git commit --signoff -m "feat: add proxyID to RuntimeInfo and route fields to KillRequest proto"
```

---

## Task 2: Gap 1 — Observer Local-Only Sync

**Files:**
- Modify: `functionsystem/src/function_proxy/common/observer/observer_actor.cpp` (lines 80–83)
- Test: `functionsystem/tests/unit/function_proxy/common/observer/control_plane_observer_test.cpp`

**Context:** `Register()` unconditionally calls `Sync(INSTANCE_PATH_PREFIX)` at line 80, loading all instances into every proxy's state machine. In DR mode only locally-owned instances are needed. The existing DR gate at line 105 (INSTANCE_ROUTE watch) is the pattern to follow.

`TransToInstanceInfoFromJson` is the correct decoding API (see `observer_actor.cpp` line 209). Do NOT use `ParseFromString` — instance records are stored as JSON.

- [ ] **Step 1: Write failing test**

In `control_plane_observer_test.cpp`, add a test that:
- Enables `DirectRoutingConfig` in DR mode
- Sets up two instances in the mock meta storage: one owned by `GetProxyID()` and one owned by a different proxy
- Calls `Register()`
- Asserts that only the locally-owned instance is loaded into the instance control view

```cpp
TEST_F(ObserverTest, DRModeLocalOnlySyncFiltersNonLocalInstances) {
    // Setup: DR mode enabled
    auto drGuard = DirectRoutingConfig::EnableForTest();

    // Two instances in mock etcd: one local, one remote
    resources::InstanceInfo localInst;
    localInst.set_instanceid("local-inst-001");
    localInst.set_functionproxyid(nodeID_);  // nodeID_ is the member field; ObserverActor has no GetProxyID()

    resources::InstanceInfo remoteInst;
    remoteInst.set_instanceid("remote-inst-002");
    remoteInst.set_functionproxyid("other-proxy-id");

    // Populate mock storage (serialized as JSON via InstanceInfoToJson)
    SetupMockInstances({localInst, remoteInst});

    observer_->Register();
    WaitForSyncDone();

    // Assert: only local instance loaded
    EXPECT_NE(nullptr, instanceControlView_->GetInstance("local-inst-001"));
    EXPECT_EQ(nullptr, instanceControlView_->GetInstance("remote-inst-002"));
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T DRModeLocalOnlySyncFiltersNonLocalInstances"`
Expected: FAIL (all instances are currently loaded)

- [ ] **Step 3: Implement local-filtered sync in DR mode**

In `observer_actor.cpp` lines 78–84 (inside `Register()`), replace:

```cpp
auto synced = metaStorageAccessor_->Sync(INSTANCE_PATH_PREFIX, true);
UpdateInstanceEvent(synced.first, true);
YRLOG_DEBUG("sync key({}) finished", INSTANCE_PATH_PREFIX);
instanceSyncDone_.SetValue(true);
```

With:

```cpp
if (!DirectRoutingConfig::IsEnabled()) {
    auto synced = metaStorageAccessor_->Sync(INSTANCE_PATH_PREFIX, true);
    UpdateInstanceEvent(synced.first, true);
    YRLOG_DEBUG("sync key({}) finished", INSTANCE_PATH_PREFIX);
    instanceSyncDone_.SetValue(true);
} else {
    // DR mode: sync all then filter to locally-owned instances for crash recovery.
    // Non-owner proxies rely on route cache; they don't need other proxies' instances.
    auto synced = metaStorageAccessor_->Sync(INSTANCE_PATH_PREFIX, true);
    std::vector<WatchEvent> localEvents;
    for (const auto &event : synced.first) {
        resources::InstanceInfo info;
        if (TransToInstanceInfoFromJson(event.kv.value(), info) &&
            info.functionproxyid() == nodeID_) {  // nodeID_ is the member; ObserverActor has no GetProxyID()
            localEvents.push_back(event);
        }
    }
    UpdateInstanceEvent(localEvents, true);
    YRLOG_DEBUG("DR mode: sync key({}) finished, loaded {} local instances",
                INSTANCE_PATH_PREFIX, localEvents.size());
    instanceSyncDone_.SetValue(true);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T DRModeLocalOnlySyncFiltersNonLocalInstances"`
Expected: PASS

- [ ] **Step 5: Run full observer test suite**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T ObserverTest*"`
Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add functionsystem/src/function_proxy/common/observer/observer_actor.cpp
git add functionsystem/tests/unit/function_proxy/common/observer/control_plane_observer_test.cpp
git commit --signoff -m "feat(gap1): DR mode local-only instance sync in observer_actor"
```

---

## Task 3: Gap 2 — Single-Write Persistence at RUNNING

**Files:**
- Modify: `functionsystem/src/function_proxy/common/state_machine/instance_state_machine.cpp` (lines 73–85)
- Test: `functionsystem/tests/unit/function_proxy/common/state_machine/state_machine_test.cpp`

**Context:** `GetPersistenceType()` is a static function at lines 73–85. In DR mode, SCHEDULING and CREATING writes are wasted I/O; only RUNNING (which carries `routeAddress`) is meaningful. FAILED/EXITED must still write for crash recovery. The non-DR code path must be unchanged.

**Critical edge case**: If an instance fails before ever reaching RUNNING (no prior etcd entry), the FAILED write must succeed with upsert semantics. Verify `metaStorageAccessor_` uses `put` (upsert), not conditional update.

- [ ] **Step 1: Write failing tests**

In `state_machine_test.cpp`:

```cpp
// Test 1: DR mode RUNNING → PERSISTENT_ALL
TEST(GetPersistenceTypeTest, DRModeRunningReturnsPersistentAll) {
    auto drGuard = DirectRoutingConfig::EnableForTest();
    resources::InstanceInfo info;
    info.mutable_instancestatus()->set_code(static_cast<int32_t>(InstanceState::RUNNING));
    EXPECT_EQ(PersistenceType::PERSISTENT_ALL, GetPersistenceTypeForTest(info, true));
    EXPECT_EQ(PersistenceType::PERSISTENT_ALL, GetPersistenceTypeForTest(info, false));
}

// Test 2: DR mode SCHEDULING → PERSISTENT_NOT
TEST(GetPersistenceTypeTest, DRModeSchedulingReturnsPersistentNot) {
    auto drGuard = DirectRoutingConfig::EnableForTest();
    resources::InstanceInfo info;
    info.mutable_instancestatus()->set_code(static_cast<int32_t>(InstanceState::SCHEDULING));
    EXPECT_EQ(PersistenceType::PERSISTENT_NOT, GetPersistenceTypeForTest(info, true));
}

// Test 3: DR mode CREATING → PERSISTENT_NOT
TEST(GetPersistenceTypeTest, DRModeCreatingReturnsPersistentNot) {
    auto drGuard = DirectRoutingConfig::EnableForTest();
    resources::InstanceInfo info;
    info.mutable_instancestatus()->set_code(static_cast<int32_t>(InstanceState::CREATING));
    EXPECT_EQ(PersistenceType::PERSISTENT_NOT, GetPersistenceTypeForTest(info, true));
}

// Test 4: DR mode FAILED → PERSISTENT_ALL (crash recovery)
TEST(GetPersistenceTypeTest, DRModeFailedReturnsPersistentAll) {
    auto drGuard = DirectRoutingConfig::EnableForTest();
    resources::InstanceInfo info;
    info.mutable_instancestatus()->set_code(static_cast<int32_t>(InstanceState::FAILED));
    EXPECT_EQ(PersistenceType::PERSISTENT_ALL, GetPersistenceTypeForTest(info, true));
}

// Test 5: Non-DR mode is unchanged
TEST(GetPersistenceTypeTest, NonDRModeSchedulingUnchanged) {
    // DR not enabled
    resources::InstanceInfo info;
    info.mutable_instancestatus()->set_code(static_cast<int32_t>(InstanceState::SCHEDULING));
    // Existing behavior: PERSISTENT_ALL when metaStore disabled
    EXPECT_EQ(PersistenceType::PERSISTENT_ALL, GetPersistenceTypeForTest(info, false));
}
```

Note: `GetPersistenceType()` is a private static function. If it's not testable directly, test through the public interface that calls it (e.g., `TransitionTo()` or the persistence mock). Alternatively, expose it as a `friend` or move it to a testable utility.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T GetPersistenceTypeTest*"`
Expected: FAIL (DR fast-path not yet implemented)

- [ ] **Step 3: Add DR fast-path in `GetPersistenceType()`**

In `instance_state_machine.cpp` lines 73–85, add at the top of the function body:

```cpp
[[maybe_unused]] static PersistenceType GetPersistenceType(
    const resources::InstanceInfo &instanceInfo, bool isMetaStoreEnable)
{
    auto state = static_cast<InstanceState>(instanceInfo.instancestatus().code());

    // DR mode fast-path: only persist at RUNNING (carries routeAddress); skip SCHEDULING/CREATING.
    // FAILED/EXITED still write so abnormal cleanup and crash recovery remain functional.
    if (DirectRoutingConfig::IsEnabled()) {
        if (state == InstanceState::RUNNING) {
            return PersistenceType::PERSISTENT_ALL;
        }
        if (state == InstanceState::FAILED || state == InstanceState::EXITED) {
            return PersistenceType::PERSISTENT_ALL;
        }
        return PersistenceType::PERSISTENT_NOT;
    }

    // Existing non-DR logic unchanged
    bool needPersistentRoute = functionsystem::NeedUpdateRouteState(state, isMetaStoreEnable);
    // ... rest of existing code
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T GetPersistenceTypeTest*"`
Expected: All 5 tests PASS

- [ ] **Step 5: Run full state machine test suite**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T StateMachineTest*"`
Expected: All existing tests pass

- [ ] **Step 6: Commit**

```bash
git add functionsystem/src/function_proxy/common/state_machine/instance_state_machine.cpp
git add functionsystem/tests/unit/function_proxy/common/state_machine/state_machine_test.cpp
git commit --signoff -m "feat(gap2): DR mode single-write persistence at RUNNING in GetPersistenceType"
```

---

## Task 4: Gap 3 — Set proxyID in notifyresult

**Files:**
- Modify: `functionsystem/src/function_proxy/local_scheduler/instance_control/instance_ctrl_actor.cpp` (line ~6021)
- Test: `functionsystem/tests/unit/function_proxy/local_scheduler/instance_control/instance_ctrl_actor_test.cpp`

**Context:** The notifyresult callback (`RegisterCreateCallResultCallback`) at line 6020 already sets `route = GetAID().Url()` in DR mode. We need to also set `proxyID = nodeID_` (the local proxy ID captured as `nodeID` in the lambda at line 6008).

**Prerequisite:** Task 1 (proxyID field must exist in RuntimeInfo proto).

- [ ] **Step 1: Write failing test**

In `instance_ctrl_actor_test.cpp`, add a test that:
- Enables DR mode
- Triggers the notifyresult path (call result with `ERR_NONE`)
- Captures the resulting `CallResult`
- Asserts `callResult.runtimeinfo().proxyid() == nodeID_`

```cpp
TEST_F(InstanceCtrlActorTest, DRModeNotifyResultSetsProxyID) {
    auto drGuard = DirectRoutingConfig::EnableForTest();
    // Trigger createCallResult callback with success
    auto callResult = TriggerSuccessfulCallResult("test-instance-001");
    EXPECT_EQ(nodeID_, callResult.runtimeinfo().proxyid());
    EXPECT_FALSE(callResult.runtimeinfo().route().empty());
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T DRModeNotifyResultSetsProxyID"`
Expected: FAIL (`proxyid()` is empty)

- [ ] **Step 3: Add `set_proxyid` in notifyresult path**

In `instance_ctrl_actor.cpp` line 6020–6022, change:

```cpp
if (instanceInfo.lowreliability() || function_proxy::DirectRoutingConfig::IsEnabled()) {
    callResult->mutable_runtimeinfo()->set_route(aid.Url());
}
```

To:

```cpp
if (instanceInfo.lowreliability() || function_proxy::DirectRoutingConfig::IsEnabled()) {
    callResult->mutable_runtimeinfo()->set_route(aid.Url());
    callResult->mutable_runtimeinfo()->set_proxyid(nodeID);  // nodeID is captured from nodeID_
}
```

Note: `nodeID` is the lambda capture of `nodeID_` at line 6008: `nodeID(nodeID_)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T DRModeNotifyResultSetsProxyID"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add functionsystem/src/function_proxy/local_scheduler/instance_control/instance_ctrl_actor.cpp
git add functionsystem/tests/unit/function_proxy/local_scheduler/instance_control/instance_ctrl_actor_test.cpp
git commit --signoff -m "feat(gap3): set proxyID in notifyresult runtimeInfo for DR mode"
```

---

## Task 5: Gap 3 — Kill Locality Check Using KillRequest Route Fields

**Files:**
- Modify: `functionsystem/src/function_proxy/local_scheduler/instance_control/instance_ctrl_actor.cpp` (`SignalRoute()` line ~693)
- Test: `functionsystem/tests/unit/function_proxy/local_scheduler/instance_control/instance_ctrl_actor_test.cpp`

**Context:** `SignalRoute()` at line 693 determines kill locality by accessing `killCtx->instanceContext->GetInstanceInfo().functionproxyid()`. In DR mode, a non-owner proxy has no state machine, so `instanceContext` may be null. We need to add a DR fast-path at the top of `SignalRoute()` that uses `KillRequest.routeAddress` and `KillRequest.proxyID` directly.

The AID for forwarding is constructed as:
```cpp
litebus::AID(proxyID + LOCAL_SCHED_INSTANCE_CTRL_ACTOR_NAME_POSTFIX, routeAddress)
```

**Prerequisite:** Task 1 (routeAddress and proxyID fields in KillRequest).

- [ ] **Step 1: Write failing tests**

```cpp
// Test 1: DR mode with route fields → remote proxy → forwarded directly
TEST_F(InstanceCtrlActorTest, DRModeKillWithRouteForwardsToRemoteProxy) {
    auto drGuard = DirectRoutingConfig::EnableForTest();

    auto killReq = std::make_shared<KillRequest>();
    killReq->set_instanceid("remote-inst-001");
    killReq->set_signal(9);
    killReq->set_routeaddress("192.168.1.200:7788");   // remote proxy bus URL
    killReq->set_proxyid("remote-proxy-id");            // not nodeID_

    // No state machine for this instance
    EXPECT_EQ(nullptr, instanceControlView_->GetInstance("remote-inst-001"));

    // Trigger kill — should forward, not fail
    auto result = TriggerKill(killReq);
    // Verify ForwardCustomSignalRequest was called with the remote AID
    EXPECT_TRUE(WasForwardKillCalledTo("remote-proxy-id"));
}

// Test 2: DR mode with route fields matching local proxy → handle locally
TEST_F(InstanceCtrlActorTest, DRModeKillWithRouteMatchingLocalProxyHandledLocally) {
    auto drGuard = DirectRoutingConfig::EnableForTest();

    auto killReq = std::make_shared<KillRequest>();
    killReq->set_instanceid("local-inst-001");
    killReq->set_signal(9);
    killReq->set_routeaddress(localBusUrl_);  // this proxy's bus URL
    killReq->set_proxyid(nodeID_);            // this proxy's ID

    // Trigger kill — should attempt local handling
    auto result = TriggerKill(killReq);
    EXPECT_FALSE(WasForwardKillCalledTo("any-other-proxy"));
}

// Test 3: Non-DR mode with empty route → existing state machine path unchanged
TEST_F(InstanceCtrlActorTest, NonDRModeKillFallsBackToStateMachinePath) {
    // DR not enabled, no route fields in request
    auto killReq = std::make_shared<KillRequest>();
    killReq->set_instanceid("test-inst");
    killReq->set_signal(9);
    // routeAddress and proxyID left empty

    // Verify existing state machine path is taken
    auto result = TriggerKill(killReq);
    EXPECT_TRUE(WasStateMachinePathUsed());
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T DRModeKill*"`
Expected: FAIL (no DR fast-path in SignalRoute)

- [ ] **Step 3: Add DR fast-path in `SignalRoute()`**

In `instance_ctrl_actor.cpp` `SignalRoute()` function (around line 693), add at the top of the function, before the existing locality check at line 703:

```cpp
litebus::Future<std::shared_ptr<KillContext>> InstanceCtrlActor::SignalRoute(
    const std::shared_ptr<KillContext> &killCtx)
{
    if (killCtx->killRsp.code() != common::ErrorCode::ERR_NONE) {
        YRLOG_WARN("(kill)failed to check param, code: {}, message: {}", ...);
        return killCtx;
    }

    // DR mode fast-path: if KillRequest carries explicit route, use it directly.
    // Non-owner proxies have no state machine in DR mode; don't try to access instanceContext.
    if (DirectRoutingConfig::IsEnabled() && !killCtx->killRequest->routeaddress().empty()) {
        if (killCtx->killRequest->proxyid() == nodeID_) {
            // This proxy is the owner — handle locally
            killCtx->isLocal = true;
        } else {
            // Forward to owner proxy using AID constructed from KillRequest route fields
            YRLOG_INFO("{}|(kill)DR mode forwarding kill({}) to owner proxy({})",
                       killCtx->killRequest->requestid(),
                       killCtx->killRequest->instanceid(),
                       killCtx->killRequest->proxyid());
            litebus::AID ownerAID(
                killCtx->killRequest->proxyid() + LOCAL_SCHED_INSTANCE_CTRL_ACTOR_NAME_POSTFIX,
                killCtx->killRequest->routeaddress());
            // Reuse SendForwardCustomSignalRequest with the pre-built AID
            return SendForwardCustomSignalRequest(
                litebus::Option<litebus::AID>(ownerAID),
                killCtx->srcInstanceID,
                killCtx->killRequest,
                killCtx->killRequest->requestid(),
                false)
            .Then([killCtx](const KillResponse &rsp) {
                killCtx->killRsp = rsp;
                return killCtx;
            });
        }
        killCtx->killRsp = GenKillResponse(common::ErrorCode::ERR_NONE, "");
        return killCtx;
    }

    // Existing state machine path (non-DR or no route info in request)
    auto &instanceInfo = killCtx->instanceContext->GetInstanceInfo();
    if (instanceInfo.functionproxyid() != nodeID_) {
        killCtx->isLocal = false;
    } else {
        killCtx->isLocal = true;
    }
    ...
```

Note: Check the actual signature of `SendForwardCustomSignalRequest` — it takes `litebus::Option<litebus::AID>` as its first parameter (see line 797–799 in the source).

**Old-client backward compatibility (DR enabled but routeAddress empty):** If `routeAddress` is empty, the DR fast-path is skipped and code falls through to the existing state machine path. For non-owner proxies in DR mode, `instanceContext` may be null. Add an explicit null guard before the existing path:

```cpp
// After the DR fast-path block, before accessing instanceContext:
if (killCtx->instanceContext == nullptr) {
    // No state machine and no route info — cannot determine locality.
    // Fail safely: return error rather than dereferencing null.
    YRLOG_ERROR("{}|(kill)DR mode: no route info and no state machine for instance({})",
                killCtx->killRequest->requestid(),
                killCtx->killRequest->instanceid());
    killCtx->killRsp = GenKillResponse(common::ErrorCode::ERR_INTERNAL, "no route info for DR kill");
    return killCtx;
}
// Existing state machine path (non-DR, or DR with local owner having a state machine):
auto &instanceInfo = killCtx->instanceContext->GetInstanceInfo();
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T DRModeKill*"`
Expected: All 3 tests PASS

- [ ] **Step 5: Run full kill-related test suite**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T InstanceCtrlActorTest*"`
Expected: All existing tests pass

- [ ] **Step 6: Commit**

```bash
git add functionsystem/src/function_proxy/local_scheduler/instance_control/instance_ctrl_actor.cpp
git add functionsystem/tests/unit/function_proxy/local_scheduler/instance_control/instance_ctrl_actor_test.cpp
git commit --signoff -m "feat(gap3): DR mode kill locality check using KillRequest route fields"
```

---

## Task 6: Gap 3 — Go InstanceAllocationInfo and faasscheduler

**Files:**
- Modify: `go/pkg/functionscaler/types/types.go` (`Instance` struct)
- Modify: `go/pkg/common/faas_common/types/lease.go` (`InstanceAllocationInfo`)
- Modify: `go/pkg/functionscaler/faasscheduler.go` (`generateInstanceResponse`)

**Context:** The Go faasscheduler returns `InstanceAllocationInfo` (from `lease.go`) to the Go SDK via JSON. The SDK uses `RouteAddress` and `ProxyID` to fill `Kill()` params.

Key type chain:
1. `go/pkg/functionscaler/types/types.go` `Instance` struct — what `insAlloc.Instance` is
2. `go/pkg/common/faas_common/types/lease.go` `InstanceAllocationInfo` — what the SDK parses from the JSON response

**Verified:** `Instance` struct at line 391 of `go/pkg/functionscaler/types/types.go` has `FunctionProxyID` but NO `RouteAddress` field. It must be added there. `api.InstanceAllocation.RouteAddress` already exists in `api/go/libruntime/api/types.go` (verified).

**Prerequisite:** Task 1.

- [ ] **Step 1: Write failing test**

```go
// go/pkg/functionscaler/faasscheduler_test.go
func TestGenerateInstanceResponsePopulatesRouteFields(t *testing.T) {
    instance := &types.Instance{
        InstanceID:      "test-inst-001",
        FunctionProxyID: "proxy-abc",
        RouteAddress:    "10.0.0.1:7788",  // will fail until RouteAddress is added
    }
    insAlloc := &types.InstanceAllocation{Instance: instance}
    resp := generateInstanceResponse(insAlloc, nil, time.Now())
    assert.Equal(t, "proxy-abc", resp.InstanceAllocationInfo.ProxyID)
    assert.Equal(t, "10.0.0.1:7788", resp.InstanceAllocationInfo.RouteAddress)
}
```

Run: `docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong/go && go test ./pkg/functionscaler/... -run TestGenerateInstanceResponsePopulatesRouteFields -v"`
Expected: FAIL (compile error: `types.Instance` has no `RouteAddress` field)

- [ ] **Step 2: Add `RouteAddress` to `Instance` struct in `types.go`**

In `go/pkg/functionscaler/types/types.go`, in the `Instance` struct (line 391), add after `FunctionProxyID`:

```go
type Instance struct {
    // ... existing fields ...
    FunctionProxyID   string
    RouteAddress      string  // litebus bus URL of owner proxy, for DR kill routing (new)
}
```

Also update `Copy()` at line 414 to include the new field:
```go
RouteAddress:      i.RouteAddress,
```

Find where `Instance` is populated from proto `InstanceInfo` (search for assignments of `.FunctionProxyID =`) and add:
```go
instance.RouteAddress = instanceInfo.RouteAddress  // InstanceInfo.routeAddress proto field 38
```

- [ ] **Step 3: Add `RouteAddress` and `ProxyID` to `InstanceAllocationInfo` in lease.go**

```go
// go/pkg/common/faas_common/types/lease.go
type InstanceAllocationInfo struct {
    // ... existing fields ...
    FunctionProxyID string `json:"functionProxyID"`
    LeaseInterval   int64  `json:"leaseInterval"`
    // new fields for direct routing kill support
    RouteAddress    string `json:"routeAddress"`  // litebus bus URL of owner proxy
    ProxyID         string `json:"proxyID"`       // functionProxyID of owner proxy
    // ... rest ...
}
```

- [ ] **Step 4: Populate in `generateInstanceResponse()` in faasscheduler.go**

In `faasscheduler.go` lines 1141–1160:

```go
return &commonTypes.InstanceResponse{
    InstanceAllocationInfo: commonTypes.InstanceAllocationInfo{
        // ... existing fields ...
        FunctionProxyID: insAlloc.Instance.FunctionProxyID,
        RouteAddress:    insAlloc.Instance.RouteAddress,    // new
        ProxyID:         insAlloc.Instance.FunctionProxyID, // reuse proxy ID as ProxyID
    },
    // ...
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong/go && go test ./pkg/functionscaler/... -run TestGenerateInstanceResponsePopulatesRouteFields -v"`
Expected: PASS

- [ ] **Step 6: Run full Go tests in the affected packages**

Run: `docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong/go && go test ./pkg/functionscaler/... ./pkg/common/... -v"`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add go/pkg/functionscaler/types/types.go
git add go/pkg/common/faas_common/types/lease.go
git add go/pkg/functionscaler/faasscheduler.go
git commit --signoff -m "feat(gap3): add RouteAddress to Instance and propagate through InstanceAllocationInfo"
```

---

## Task 7: Gap 3 — Go CGo Kill Route Chain

**Files:**
- Modify: `api/go/libruntime/cpplibruntime/clibruntime.h`
- Modify: `api/go/libruntime/clibruntime/clibruntime.go`
- Modify: `api/go/libruntime/libruntimesdkimpl/libruntimesdkimpl.go`
- Test: `api/go/libruntime/clibruntime/clibruntime_test.go`

**Context:** Current `CKill(char *instanceId, int sigNo, CBuffer cData)` has no route params. Current `CInstanceAllocation` has: `functionId`, `funcSig`, `instanceId`, `leaseId`, `tLeaseInterval`.

Changes needed:
1. Add `routeAddress`, `proxyID` to `CInstanceAllocation` struct so `CAcquireInstance` can return them
2. Change `CKill` signature to accept `routeAddress` and `proxyID`
3. Update all Go-side helpers that touch these structs: `AcquireInstance()`, `Kill()`, `freeCInstanceAllocation()`, `cCInstanceAllocation()`

**C++ ABI changes (required, not optional):** The C++ implementation file `cpplibruntime.cpp` implements `CKill` and `CAcquireInstance`. Both must be updated as first-class implementation steps — the plan covers them in Step 4 below.

Find the file first: `grep -rl "CKill\|CAcquireInstance" --include="*.cpp"` in the yuanrong repo.

**Prerequisite:** Task 1, Task 6.

- [ ] **Step 1: Write failing tests (behavioral + compile)**

**Test A — behavioral: AcquireInstance returns RouteAddress/ProxyID**
```go
// api/go/libruntime/clibruntime/clibruntime_test.go
func TestAcquireInstanceReturnsRouteFields(t *testing.T) {
    // Use a mock/stub C layer that returns known values for routeAddress and proxyID
    // If a test helper exists that sets up a fake CAcquireInstance response, use it.
    // Minimum: verify that the conversion code compiles and maps fields correctly.
    cAlloc := C.CInstanceAllocation{
        instanceId:   C.CString("inst-001"),
        routeAddress: C.CString("10.0.0.1:7788"),
        proxyID:      C.CString("proxy-abc"),
    }
    result := convertCInstanceAllocation(&cAlloc)  // internal helper if available
    assert.Equal(t, "10.0.0.1:7788", result.RouteAddress)
    assert.Equal(t, "proxy-abc", result.ProxyID)
}
```

**Test B — compile validation: Kill() accepts route params**
```go
func TestKillSignatureAcceptsRouteParams(t *testing.T) {
    // Primary purpose: verify Kill() compiles with 5 params
    err := Kill("test-inst", 9, nil, "10.0.0.1:7788", "proxy-abc")
    _ = err  // CKill may fail if C runtime not initialized — expected in unit test
}
```

Run: `docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong/api/go && go build ./libruntime/..."`
Expected: FAIL (Kill() doesn't accept 5 params yet)

- [ ] **Step 2: Update `CInstanceAllocation` and `CKill` in clibruntime.h**

```c
// api/go/libruntime/cpplibruntime/clibruntime.h
typedef struct tagCInstanceAllocation {
    char *functionId;
    char *funcSig;
    char *instanceId;
    char *leaseId;
    int   tLeaseInterval;
    char *routeAddress;  // litebus bus URL of owner proxy (new)
    char *proxyID;       // functionProxyID of owner proxy (new)
} CInstanceAllocation;

// Update CKill signature:
CErrorInfo CKill(char *instanceId, int sigNo, CBuffer cData, char *routeAddress, char *proxyID);
```

- [ ] **Step 3: Update all CGo helper functions in clibruntime.go**

**`AcquireInstance()`** — read new fields from C struct:
```go
return api.InstanceAllocation{
    FuncSig:       CSafeGoString(instanceAllocation.funcSig),
    FuncKey:       CSafeGoString(instanceAllocation.functionId),
    InstanceID:    CSafeGoString(instanceAllocation.instanceId),
    LeaseID:       CSafeGoString(instanceAllocation.leaseId),
    LeaseInterval: int64(instanceAllocation.tLeaseInterval),
    RouteAddress:  CSafeGoString(instanceAllocation.routeAddress),  // new
    ProxyID:       CSafeGoString(instanceAllocation.proxyID),       // new
}, nil
```

**`Kill()`** — add route params, pass to `C.CKill`:
```go
func Kill(instanceID string, signo int, data []byte, routeAddress string, proxyID string) error {
    cInstanceID := C.CString(instanceID)
    defer C.free(unsafe.Pointer(cInstanceID))
    cRouteAddress := C.CString(routeAddress)
    defer C.free(unsafe.Pointer(cRouteAddress))
    cProxyID := C.CString(proxyID)
    defer C.free(unsafe.Pointer(cProxyID))

    cSigno := C.int(signo)
    cData, cDataLen := ByteSliceToCBinaryData(data)
    if cData != nil {
        defer C.free(cData)
    }
    cBuf := C.CBuffer{buffer: cData, size_buffer: C.int64_t(cDataLen)}
    cErr := C.CKill(cInstanceID, cSigno, cBuf, cRouteAddress, cProxyID)
    code := int(cErr.code)
    if code != 0 {
        return codeNotZeroErr(code, cErr, "kill instance: ")
    }
    return nil
}
```

**`freeCInstanceAllocation()`** — free new fields:
```go
func freeCInstanceAllocation(cInstanceAllocation *C.CInstanceAllocation) {
    CSafeFree(cInstanceAllocation.funcSig)
    CSafeFree(cInstanceAllocation.functionId)
    CSafeFree(cInstanceAllocation.instanceId)
    CSafeFree(cInstanceAllocation.leaseId)
    CSafeFree(cInstanceAllocation.routeAddress)  // new
    CSafeFree(cInstanceAllocation.proxyID)       // new
}
```

**`cCInstanceAllocation()`** — set new fields when converting Go→C (used in `ReleaseInstance`):
```go
func cCInstanceAllocation(instanceAllocation api.InstanceAllocation) *C.CInstanceAllocation {
    cInstanceAlloc := C.CInstanceAllocation{
        functionId:     C.CString(instanceAllocation.FuncKey),
        funcSig:        C.CString(instanceAllocation.FuncSig),
        instanceId:     C.CString(instanceAllocation.InstanceID),
        leaseId:        C.CString(instanceAllocation.LeaseID),
        tLeaseInterval: C.int(instanceAllocation.LeaseInterval),
        routeAddress:   C.CString(instanceAllocation.RouteAddress),  // new (empty string OK)
        proxyID:        C.CString(instanceAllocation.ProxyID),       // new (empty string OK)
    }
    return &cInstanceAlloc
}
```

Note: `C.CString("")` for empty strings is safe — it allocates a 1-byte null-terminated string. `CSafeFree` handles null checks.

- [ ] **Step 4: Update `libruntimesdkimpl.go`**

**Critical:** `libruntimeSDKImpl` is currently an empty struct (`type libruntimeSDKImpl struct{}`). Adding `routeCache` means updating the struct definition — `NewLibruntimeSDKImpl()` needs no change since `sync.Map` is zero-value safe.

```go
// BEFORE (current state in libruntimesdkimpl.go line 30):
// type libruntimeSDKImpl struct{}

// AFTER — add routeCache field:
type libruntimeSDKImpl struct {
    routeCache sync.Map  // instanceID → [2]string{routeAddress, proxyID}
}

// NewLibruntimeSDKImpl unchanged — sync.Map is zero-value initialized:
// func NewLibruntimeSDKImpl() api.LibruntimeAPI { return &libruntimeSDKImpl{} }

// AcquireInstance — wrap existing delegation to cache route info (currently line 54):
func (l *libruntimeSDKImpl) AcquireInstance(state string, funcMeta api.FunctionMeta,
    acquireOpt api.InvokeOptions) (api.InstanceAllocation, error) {
    allocation, err := clibruntime.AcquireInstance(state, funcMeta, acquireOpt)
    if err == nil && allocation.InstanceID != "" {
        l.routeCache.Store(allocation.InstanceID, [2]string{allocation.RouteAddress, allocation.ProxyID})
    }
    return allocation, err
}

// Kill — retrieve route info, then call clibruntime.Kill with route params (currently line 64):
func (l *libruntimeSDKImpl) Kill(instanceID string, signal int, payload []byte, invokeOpt api.InvokeOptions) error {
    _ = invokeOpt
    routeAddress, proxyID := "", ""
    if v, ok := l.routeCache.Load(instanceID); ok {
        pair := v.([2]string)
        routeAddress, proxyID = pair[0], pair[1]
    }
    return clibruntime.Kill(instanceID, signal, payload, routeAddress, proxyID)
}
```

- [ ] **Step 5: Update C++ ABI helpers in `cpplibruntime.cpp`**

Find the C++ libruntime implementation file:
```bash
grep -rl "CKill\|CAcquireInstance" --include="*.cpp"
```

Two functions require changes:

**`CAcquireInstance` (or equivalent):** After obtaining the schedule response that contains `InstanceInfo`, populate the new fields:
```cpp
// In CAcquireInstance or InsAllocationToCInsAllocation helper:
cInstanceAlloc.routeAddress = strdup(instanceInfo.routeaddress().c_str());
cInstanceAlloc.proxyID      = strdup(instanceInfo.functionproxyid().c_str());
```

**`CKill`:** Accept and forward route params to the `KillRequest` proto:
```cpp
CErrorInfo CKill(char *instanceId, int sigNo, CBuffer cData, char *routeAddress, char *proxyID)
{
    // Existing setup ...
    KillRequest req;
    req.set_instanceid(instanceId);
    req.set_signal(sigNo);
    if (routeAddress != nullptr && strlen(routeAddress) > 0) {
        req.set_routeaddress(routeAddress);
    }
    if (proxyID != nullptr && strlen(proxyID) > 0) {
        req.set_proxyid(proxyID);
    }
    // Existing send logic ...
}
```

- [ ] **Step 6: Verify build compiles cleanly**

Run: `docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong/api/go && go build ./libruntime/..."`
Expected: Build succeeds (CGo ABI matches both Go header and C++ impl)

- [ ] **Step 7: Run Go libruntime tests**

Run: `docker exec compile bash -c "source /etc/profile.d/buildtools.sh && cd /Users/robbluo/code/yuanrong/api/go && go test ./libruntime/... -v"`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add api/go/libruntime/cpplibruntime/clibruntime.h
git add api/go/libruntime/clibruntime/clibruntime.go
git add api/go/libruntime/libruntimesdkimpl/libruntimesdkimpl.go
git add api/go/libruntime/clibruntime/clibruntime_test.go
# also add the cpplibruntime.cpp file once located
git commit --signoff -m "feat(gap3): propagate route info through Go CGo Kill chain for DR mode"
```

---

## Task 8: Gap 4 — DeleteRequestFuture: Sub-scenario B Cleanup

**Files:**
- Modify: `functionsystem/src/function_proxy/local_scheduler/instance_control/instance_ctrl_actor.cpp` (`DeleteRequestFuture()` lines 6223–6236)
- Test: `functionsystem/tests/unit/function_proxy/local_scheduler/instance_control/instance_ctrl_actor_test.cpp`

**Context:** `DeleteRequestFuture()` fires when the domain scheduler responds to a schedule request. Currently (lines 6231–6234) it calls `stateMachine->ReleaseOwner()` on failure. In DR mode, when the domain returns a failure (e.g., local resources insufficient), the state machine must be fully deleted — `ReleaseOwner()` alone is insufficient because no etcd DELETE event will ever arrive to trigger cleanup.

This is Sub-scenario B: Proxy A is acting as local scheduler, gets a request from domain, creates state machine, but returns the request to domain due to insufficient resources.

- [ ] **Step 1: Write failing test**

```cpp
TEST_F(InstanceCtrlActorTest, DRModeDeleteRequestFutureOnFailureDeletesStateMachine) {
    auto drGuard = DirectRoutingConfig::EnableForTest();

    // Setup: create a state machine in SCHEDULING state
    const std::string instanceID = "sched-fail-inst-001";
    const std::string requestID = "req-001";
    SetupSchedulingStateMachine(instanceID, requestID);

    // Verify state machine exists
    ASSERT_NE(nullptr, instanceControlView_->GetInstance(instanceID));

    // Simulate schedule failure from domain
    ScheduleResponse failResponse;
    failResponse.set_code(1);  // non-zero = failure
    TriggerDeleteRequestFuture(requestID, instanceID, failResponse);

    // In DR mode: state machine must be deleted
    EXPECT_EQ(nullptr, instanceControlView_->GetInstance(instanceID));
}

TEST_F(InstanceCtrlActorTest, NonDRModeDeleteRequestFutureOnFailureReleasesOwner) {
    // DR NOT enabled
    const std::string instanceID = "sched-fail-inst-002";
    const std::string requestID = "req-002";
    SetupSchedulingStateMachine(instanceID, requestID);

    ScheduleResponse failResponse;
    failResponse.set_code(1);
    TriggerDeleteRequestFuture(requestID, instanceID, failResponse);

    // Non-DR mode: state machine stays, owner released (ReleaseOwner called)
    auto sm = instanceControlView_->GetInstance(instanceID);
    ASSERT_NE(nullptr, sm);
    EXPECT_FALSE(sm->HasOwner());
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T DRModeDeleteRequestFuture*"`
Expected: FAIL

- [ ] **Step 3: Modify `DeleteRequestFuture()` for Sub-scenario B**

Replace lines 6223–6236 with:

```cpp
litebus::Future<ScheduleResponse> InstanceCtrlActor::DeleteRequestFuture(
    const litebus::Future<ScheduleResponse> &scheduleResponse,
    const std::string &requestID,
    const std::shared_ptr<messages::ScheduleRequest> &scheduleReq)
{
    instanceControlView_->DeleteRequestFuture(requestID);

    auto instanceID = scheduleReq->instance().instanceid();
    auto stateMachine = instanceControlView_->GetInstance(instanceID);
    if (stateMachine == nullptr) {
        return scheduleResponse;
    }

    bool scheduleFailed = scheduleResponse.IsError() || scheduleResponse.Get().code() != 0;
    if (scheduleFailed && stateMachine->GetInstanceState() == InstanceState::SCHEDULING) {
        if (DirectRoutingConfig::IsEnabled()) {
            // Sub-scenario B: failure is definitive — this proxy is NOT the owner.
            // Delete immediately; no etcd event will ever clean this up in DR mode.
            YRLOG_INFO("{}|DR mode: cleanup rejected schedule SM for instance({})",
                       requestID, instanceID);
            instanceControlView_->Delete(instanceID, 0);
        } else {
            // Non-DR mode: release owner for retry; etcd events handle eventual cleanup
            stateMachine->ReleaseOwner();
        }
    }
    // Sub-scenario A (success): handled separately via runtimePromise timer (see Task 9)

    return scheduleResponse;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T DRModeDeleteRequestFuture*"`
Expected: Both tests PASS

- [ ] **Step 5: Commit**

```bash
git add functionsystem/src/function_proxy/local_scheduler/instance_control/instance_ctrl_actor.cpp
git add functionsystem/tests/unit/function_proxy/local_scheduler/instance_control/instance_ctrl_actor_test.cpp
git commit --signoff -m "feat(gap4b): DR mode immediate SM cleanup on schedule failure in DeleteRequestFuture"
```

---

## Task 9: Gap 4 — runtimePromise GC Timer for Sub-scenario A

**Files:**
- Modify: `functionsystem/src/function_proxy/local_scheduler/instance_control/instance_ctrl_actor.cpp` (after `DeleteRequestFuture()`)
- Modify: `functionsystem/src/function_proxy/local_scheduler/instance_control/instance_ctrl_actor.h`
- Test: `functionsystem/tests/unit/function_proxy/local_scheduler/instance_control/instance_ctrl_actor_test.cpp`

**Context:** Sub-scenario A: domain assigns the instance to a **different** proxy (schedule succeeds). The `runtimePromise` is stored in `createRequestRuntimeFuture_` at line ~1443 (`InsertRequestFuture()`). It waits for `OnCallResult` to fire (instance becomes RUNNING). In DR mode, if the instance is on a remote proxy, `OnCallResult` never arrives here, so `runtimePromise` hangs forever and the state machine leaks.

**Fix:** After schedule success in DR mode, use `litebus::AsyncAfter` (the actual timer API in this codebase — verified at lines 239, 822) to schedule a dedicated method `GCOrphanStateMachine`. `litebus::Delay` does NOT exist in this codebase. The timer method is a named method on `InstanceCtrlActor`, not a lambda, because `litebus::AsyncAfter` takes method pointers, not closures.

`INSTANCE_CREATE_GC_TIMEOUT_MS` is a constant (120000ms = 120s) long enough that no legitimate local instance is still in SCHEDULING when the timer fires.

**Prerequisite:** Task 8 must be committed first (modifies the same `DeleteRequestFuture()` function).

- [ ] **Step 1: Write failing tests**

```cpp
// Test 1: DR mode, schedule success, remote owner → SM deleted after GC timer fires
TEST_F(InstanceCtrlActorTest, DRModeSubScenarioADeletesOrphanSMAfterTimeout) {
    auto drGuard = DirectRoutingConfig::EnableForTest();
    const std::string instanceID = "remote-inst-A-001";
    const std::string requestID = "req-A-001";

    SetupSchedulingStateMachine(instanceID, requestID);
    ScheduleResponse successResponse;
    successResponse.set_code(0);

    TriggerDeleteRequestFuture(requestID, instanceID, successResponse);

    // SM still exists immediately after schedule success
    ASSERT_NE(nullptr, instanceControlView_->GetInstance(instanceID));

    // Fire the GC timer directly (test calls GCOrphanStateMachine to simulate timer expiry)
    actor_->GCOrphanStateMachine(instanceID, requestID);

    // After GC: SM deleted (never transitioned past SCHEDULING)
    EXPECT_EQ(nullptr, instanceControlView_->GetInstance(instanceID));
}

// Test 2: DR mode, schedule success, local owner → GC timer fires, SM already RUNNING → not deleted
TEST_F(InstanceCtrlActorTest, DRModeSubScenarioADoesNotDeleteLocalInstanceAfterTimeout) {
    auto drGuard = DirectRoutingConfig::EnableForTest();
    const std::string instanceID = "local-inst-A-002";
    const std::string requestID = "req-A-002";

    SetupSchedulingStateMachine(instanceID, requestID);
    ScheduleResponse successResponse;
    successResponse.set_code(0);
    TriggerDeleteRequestFuture(requestID, instanceID, successResponse);

    // Simulate local OnCallResult → SM transitions to RUNNING
    TransitionToRunning(instanceID);

    // GC timer fires: SM is RUNNING, not SCHEDULING → no deletion
    actor_->GCOrphanStateMachine(instanceID, requestID);
    EXPECT_NE(nullptr, instanceControlView_->GetInstance(instanceID));
}

// Test 3: Non-DR mode, schedule success → GCOrphanStateMachine is a no-op
TEST_F(InstanceCtrlActorTest, NonDRModeGCOrphanStateMachineIsNoOp) {
    // DR NOT enabled
    const std::string instanceID = "inst-B-003";
    const std::string requestID = "req-B-003";
    SetupSchedulingStateMachine(instanceID, requestID);

    // Call GCOrphanStateMachine directly — should do nothing in non-DR mode
    actor_->GCOrphanStateMachine(instanceID, requestID);
    EXPECT_NE(nullptr, instanceControlView_->GetInstance(instanceID));
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T DRModeSubScenarioA* NonDRModeGCOrphan*"`
Expected: FAIL (`GCOrphanStateMachine` doesn't exist yet)

- [ ] **Step 3: Add constant, new method declaration, and timer registration**

**In `instance_ctrl_actor.h`**, add to the private section:

```cpp
// GC timer for DR mode: cleans up orphaned state machines that were scheduled to remote proxy
static constexpr uint64_t INSTANCE_CREATE_GC_TIMEOUT_MS = 120000;  // 120 seconds
void GCOrphanStateMachine(const std::string &instanceID, const std::string &requestID);
```

**In `instance_ctrl_actor.cpp`**, add the method implementation:

```cpp
void InstanceCtrlActor::GCOrphanStateMachine(const std::string &instanceID,
                                              const std::string &requestID)
{
    if (!DirectRoutingConfig::IsEnabled()) {
        return;
    }
    auto stateMachine = instanceControlView_->GetInstance(instanceID);
    if (stateMachine == nullptr) {
        return;  // already cleaned up by another path
    }
    if (stateMachine->GetInstanceState() == InstanceState::SCHEDULING) {
        YRLOG_WARN("{}|DR mode: instance({}) stuck in SCHEDULING after {}ms, "
                   "assuming remote owner, cleanup orphan SM",
                   requestID, instanceID, INSTANCE_CREATE_GC_TIMEOUT_MS);
        instanceControlView_->Delete(instanceID, 0);
    }
}
```

**In `DeleteRequestFuture()`**, after the `scheduleFailed` block (after Task 8 code), add:

```cpp
// Sub-scenario A: schedule succeeded in DR mode.
// If this proxy is not the owner, OnCallResult never arrives and the SM leaks.
// Register GCOrphanStateMachine to run after INSTANCE_CREATE_GC_TIMEOUT_MS.
// If SM is still SCHEDULING then, it's a remote-owner orphan.
if (!scheduleFailed && DirectRoutingConfig::IsEnabled() && stateMachine != nullptr) {
    litebus::AsyncAfter(INSTANCE_CREATE_GC_TIMEOUT_MS, GetAID(),
                        &InstanceCtrlActor::GCOrphanStateMachine, instanceID, requestID);
}
```

Note: `litebus::AsyncAfter(delayMs, aid, methodPtr, args...)` is the correct API (verified at line 239 and 822 in instance_ctrl_actor.cpp). Do NOT use `litebus::Delay` — it does not exist.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T DRModeSubScenarioA* NonDRModeGCOrphan*"`
Expected: All 3 tests PASS

- [ ] **Step 5: Run full test suite for instance_ctrl_actor**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4 -T InstanceCtrlActorTest*"`
Expected: All tests pass

- [ ] **Step 6: Run full unit test suite**

Run: `docker exec compile bash -c "cd /Users/robbluo/code/yuanrong-functionsystem && bash run.sh test -j 4"`
Expected: Full suite passes (pre-existing failures excluded)

- [ ] **Step 7: Commit**

```bash
git add functionsystem/src/function_proxy/local_scheduler/instance_control/instance_ctrl_actor.h
git add functionsystem/src/function_proxy/local_scheduler/instance_control/instance_ctrl_actor.cpp
git add functionsystem/tests/unit/function_proxy/local_scheduler/instance_control/instance_ctrl_actor_test.cpp
git commit --signoff -m "feat(gap4a): DR mode AsyncAfter GC timer for remote-owner orphan SM"
```

---

## Verification Checklist

Before declaring the implementation complete:

- [ ] All 4 gaps have corresponding tests that were red before the fix and green after
- [ ] Full C++ unit test suite passes: `bash run.sh test -j 4`
- [ ] Go build compiles: `go build ./...` in `yuanrong/go` and `yuanrong/api/go`
- [ ] Go unit tests pass: `go test ./...` in both Go directories
- [ ] Proto regeneration was done and generated files are committed
- [ ] No existing tests were broken (pre-existing failures are acceptable and documented)

## Known Pre-existing Test Failures

The following tests were failing before this work and are NOT caused by these changes:
- `BuildTest.GeneratePosixEnvsTest`
- `DefaultScorerTest.DefaultScorer`
- `IAMActorRoleTest.ParseRoleNotPresentInPayload`

These are pre-existing issues unrelated to direct routing.
