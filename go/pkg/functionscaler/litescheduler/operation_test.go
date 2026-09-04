/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

// Package litescheduler -
package litescheduler

import (
	"encoding/json"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/smartystreets/goconvey/convey"
	"yuanrong.org/kernel/pkg/common/faas_common/constant"
	"yuanrong.org/kernel/pkg/common/faas_common/statuscode"
	commonTypes "yuanrong.org/kernel/pkg/common/faas_common/types"
	"yuanrong.org/kernel/pkg/functionscaler/config"
	"yuanrong.org/kernel/pkg/functionscaler/types"
)

func newTestPool(t *testing.T) *LiteFunctionPool {
	p := &LiteFunctionPool{
		funcKey:    "t1/fA/v1",
		funcSpec:   &types.FunctionSpecification{FuncKey: "t1/fA/v1"},
		instances:  map[string]*LiteInstance{},
		sessions:   map[string]*sessionBinding{},
		dispatcher: &concurrencyDispatcher{},
	}
	p.instances["ins1"] = &LiteInstance{InstanceID: "ins1", FuncKey: "t1/fA/v1", Capacity: 2, InUse: 0,
		Status: InstanceStatusRunning, FuncSig: "sig"}
	p.instances["ins2"] = &LiteInstance{InstanceID: "ins2", FuncKey: "t1/fA/v1", Capacity: 2, InUse: 0,
		Status: InstanceStatusRunning, FuncSig: "sig"}
	return p
}

func newLiteReacquireMetrics(t *testing.T, funcKey, sessionID string,
	sessionTTL int) *types.InstanceThreadMetrics {
	t.Helper()
	sessionData, err := json.Marshal(commonTypes.InstanceSessionConfig{
		SessionID: sessionID, SessionTTL: sessionTTL, Concurrency: 1,
	})
	if err != nil {
		t.Fatalf("marshal session config: %v", err)
	}
	reacquireData, err := json.Marshal(map[string][]byte{
		constant.InstanceSessionConfig: sessionData,
	})
	if err != nil {
		t.Fatalf("marshal reacquire data: %v", err)
	}
	return &types.InstanceThreadMetrics{FunctionKey: funcKey, ReacquireData: reacquireData}
}

func marshalRetainMetrics(t *testing.T, metrics interface{}) []byte {
	t.Helper()
	data, err := json.Marshal(metrics)
	if err != nil {
		t.Fatalf("marshal retain metrics: %v", err)
	}
	return data
}

func TestLiteTTL(t *testing.T) {
	originalLeaseSpan := config.GlobalConfig.LeaseSpan
	defer func() { config.GlobalConfig.LeaseSpan = originalLeaseSpan }()

	tests := []struct {
		name      string
		leaseSpan int
		expected  time.Duration
	}{
		{name: "zero uses minimum", leaseSpan: 0, expected: types.MinLeaseInterval},
		{name: "below minimum uses minimum", leaseSpan: 100, expected: types.MinLeaseInterval},
		{name: "minimum is retained", leaseSpan: 500, expected: types.MinLeaseInterval},
		{name: "value above minimum is retained", leaseSpan: 1000, expected: time.Second},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			config.GlobalConfig.LeaseSpan = tt.leaseSpan
			if actual := liteTTL(); actual != tt.expected {
				t.Errorf("liteTTL() = %s, want %s", actual, tt.expected)
			}
		})
	}
}

func TestAcquireSessionSticky(t *testing.T) {
	convey.Convey("same session returns same instance", t, func() {
		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := newTestPool(t)
		ls.pools["t1/fA/v1"] = pool
		req := &LiteRequest{Op: "acquire", FuncKey: "t1/fA/v1", SessionID: "sess1", SessionTTL: 30, Concurrency: 1, TenantID: "t1", TraceID: "tr"}
		resp1 := ls.handleAcquire(req)
		convey.So(resp1.ErrorCode, convey.ShouldEqual, constant.InsReqSuccessCode)
		id1 := resp1.InstanceID
		resp2 := ls.handleAcquire(req)
		convey.So(resp2.InstanceID, convey.ShouldEqual, id1) // sticky
	})
}

func TestReleaseReturnsToReservedKeepsSticky(t *testing.T) {
	convey.Convey("release returns the unit to the session reservation, keeps binding", t, func() {
		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := newTestPool(t)
		ls.pools["t1/fA/v1"] = pool
		req := &LiteRequest{Op: "acquire", FuncKey: "t1/fA/v1", SessionID: "sess1", SessionTTL: 30, Concurrency: 1, TenantID: "t1", TraceID: "tr"}
		resp := ls.handleAcquire(req)
		allocID := resp.ThreadID
		convey.So(pool.instances["ins1"].InUse+pool.instances["ins2"].InUse, convey.ShouldEqual, 1)
		relReq := &LiteRequest{Op: "release", AllocationIDs: []string{allocID}, FuncKey: "t1/fA/v1", TraceID: "tr"}
		ls.handleRelease(relReq)
		// Concurrency-aware: release returns to binding.reserved, NOT to the instance.
		// slot.InUse stays at 1 (reserved by session) until the session idle-unbinds.
		convey.So(pool.instances["ins1"].InUse+pool.instances["ins2"].InUse, convey.ShouldEqual, 1)
		pool.RLock()
		binding := pool.sessions["sess1"]
		pool.RUnlock()
		convey.So(binding, convey.ShouldNotBeNil)
		convey.So(binding.reserved, convey.ShouldEqual, 1)     // unit returned to reservation
		convey.So(binding.activeAllocs, convey.ShouldEqual, 0) // no in-flight allocs
	})
}

func TestRetainDoesNotChangeConcurrency(t *testing.T) {
	convey.Convey("retain refreshes TTL, no InUse change", t, func() {
		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := newTestPool(t)
		ls.pools["t1/fA/v1"] = pool
		req := &LiteRequest{Op: "acquire", FuncKey: "t1/fA/v1", SessionID: "sess1", SessionTTL: 30, Concurrency: 1, TenantID: "t1", TraceID: "tr"}
		resp := ls.handleAcquire(req)
		allocID := resp.ThreadID
		oldExpire := ls.allocations[allocID].ExpireAt
		time.Sleep(5 * time.Millisecond)
		retReq := &LiteRequest{Op: "retain", AllocationIDs: []string{allocID}, FuncKey: "t1/fA/v1", TraceID: "tr"}
		ls.handleRetain(retReq)
		convey.So(ls.allocations[allocID].ExpireAt.After(oldExpire), convey.ShouldBeTrue)
		convey.So(pool.instances["ins1"].InUse+pool.instances["ins2"].InUse, convey.ShouldEqual, 1) // unchanged
	})
}

func TestRetainReacquiresMissingAllocation(t *testing.T) {
	convey.Convey("retain miss with reacquireData restores the original lite allocation", t, func() {
		orig := config.GlobalConfig.LiteScheduler
		defer func() { config.GlobalConfig.LiteScheduler = orig }()
		config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{Enable: true, EnableAllTenants: true}

		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := newTestPool(t)
		ls.pools[pool.funcKey] = pool
		allocID := genAllocationID("sess1", "ins1", 7)
		metrics := newLiteReacquireMetrics(t, pool.funcKey, "sess1", 30)
		req := &LiteRequest{Op: "retain", AllocationIDs: []string{allocID}, TraceID: "tr",
			MetricsData: marshalRetainMetrics(t, metrics), NeedReverseLookup: true}

		data, err := ls.Process(req, req.TraceID, "", req.MetricsData)
		convey.So(err, convey.ShouldBeNil)
		resp := &commonTypes.InstanceResponse{}
		convey.So(json.Unmarshal(data, resp), convey.ShouldBeNil)
		convey.So(resp.ErrorCode, convey.ShouldEqual, constant.InsReqSuccessCode)
		convey.So(resp.ThreadID, convey.ShouldEqual, allocID)
		convey.So(resp.InstanceID, convey.ShouldEqual, "ins1")
		convey.So(ls.allocations, convey.ShouldContainKey, allocID)
		convey.So(ls.allocations[allocID].SessionID, convey.ShouldEqual, "sess1")
		convey.So(pool.instances["ins1"].InUse, convey.ShouldEqual, 1)
		convey.So(pool.sessions["sess1"].activeAllocs, convey.ShouldEqual, 1)
	})
}

func TestRetainMissWithoutReacquireData(t *testing.T) {
	convey.Convey("retain miss without reacquireData keeps LeaseIDNotFound behavior", t, func() {
		orig := config.GlobalConfig.LiteScheduler
		defer func() { config.GlobalConfig.LiteScheduler = orig }()
		config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{Enable: true, EnableAllTenants: true}

		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := newTestPool(t)
		ls.pools[pool.funcKey] = pool
		allocID := genAllocationID("sess1", "ins1", 1)
		req := &LiteRequest{Op: "retain", AllocationIDs: []string{allocID}, TraceID: "tr",
			MetricsData:       marshalRetainMetrics(t, &types.InstanceThreadMetrics{FunctionKey: pool.funcKey}),
			NeedReverseLookup: true}
		resp := ls.handleRetain(req)

		convey.So(resp.ErrorCode, convey.ShouldEqual, statuscode.LeaseIDNotFoundCode)
		convey.So(ls.allocations, convey.ShouldNotContainKey, allocID)
		convey.So(pool.instances["ins1"].InUse, convey.ShouldEqual, 0)
	})
}

func TestRetainReacquireRejectsSessionHashMismatch(t *testing.T) {
	convey.Convey("reacquireData session must match allocation ID hash", t, func() {
		orig := config.GlobalConfig.LiteScheduler
		defer func() { config.GlobalConfig.LiteScheduler = orig }()
		config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{Enable: true, EnableAllTenants: true}

		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := newTestPool(t)
		ls.pools[pool.funcKey] = pool
		allocID := genAllocationID("another-session", "ins1", 1)
		req := &LiteRequest{Op: "retain", AllocationIDs: []string{allocID}, TraceID: "tr",
			MetricsData:       marshalRetainMetrics(t, newLiteReacquireMetrics(t, pool.funcKey, "sess1", 30)),
			NeedReverseLookup: true}
		resp := ls.handleRetain(req)

		convey.So(resp.ErrorCode, convey.ShouldEqual, statuscode.LeaseIDIllegalCode)
		convey.So(ls.allocations, convey.ShouldNotContainKey, allocID)
	})
}

func TestRetainReacquireReturnsCurrentSessionOwner(t *testing.T) {
	convey.Convey("reacquire on a non-owner returns the raw owner instance ID", t, func() {
		orig := config.GlobalConfig.LiteScheduler
		defer func() { config.GlobalConfig.LiteScheduler = orig }()
		config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{Enable: true, EnableAllTenants: true}

		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{},
			ownerProxy: newTestProxyWithOwner("")}
		pool := newTestPool(t)
		ls.pools[pool.funcKey] = pool
		allocID := genAllocationID("sess1", "ins1", 1)
		req := &LiteRequest{Op: "retain", AllocationIDs: []string{allocID}, TraceID: "tr",
			MetricsData:       marshalRetainMetrics(t, newLiteReacquireMetrics(t, pool.funcKey, "sess1", 30)),
			NeedReverseLookup: true}
		resp := ls.handleRetain(req)

		convey.So(resp.ErrorCode, convey.ShouldEqual, statuscode.AcquireNonOwnerSchedulerErrorCode)
		convey.So(resp.ErrorMessage, convey.ShouldEqual, "owner-id-1")
		convey.So(ls.allocations, convey.ShouldNotContainKey, allocID)
		convey.So(pool.instances["ins1"].InUse, convey.ShouldEqual, 0)
	})
}

func TestRetainReacquireAllowsDesignatedOverCapacity(t *testing.T) {
	convey.Convey("designated allocation recovery is allowed when local capacity is full", t, func() {
		orig := config.GlobalConfig.LiteScheduler
		defer func() { config.GlobalConfig.LiteScheduler = orig }()
		config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{Enable: true, EnableAllTenants: true}

		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := newTestPool(t)
		ls.pools[pool.funcKey] = pool
		pool.instances["ins1"].InUse = pool.instances["ins1"].Capacity
		allocID := genAllocationID("sess1", "ins1", 1)
		req := &LiteRequest{Op: "retain", AllocationIDs: []string{allocID}, TraceID: "tr",
			MetricsData:       marshalRetainMetrics(t, newLiteReacquireMetrics(t, pool.funcKey, "sess1", 30)),
			NeedReverseLookup: true}
		resp := ls.handleRetain(req)

		convey.So(resp.ErrorCode, convey.ShouldEqual, constant.InsReqSuccessCode)
		convey.So(pool.instances["ins1"].InUse, convey.ShouldEqual, pool.instances["ins1"].Capacity+1)
		convey.So(ls.allocations, convey.ShouldContainKey, allocID)
	})
}

func TestConcurrentRetainReacquireIsIdempotent(t *testing.T) {
	convey.Convey("concurrent reacquire increments instance and session usage once", t, func() {
		orig := config.GlobalConfig.LiteScheduler
		defer func() { config.GlobalConfig.LiteScheduler = orig }()
		config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{Enable: true, EnableAllTenants: true}

		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := newTestPool(t)
		ls.pools[pool.funcKey] = pool
		allocID := genAllocationID("sess1", "ins1", 1)
		metricsData := marshalRetainMetrics(t, newLiteReacquireMetrics(t, pool.funcKey, "sess1", 30))
		const workers = 16
		var wg sync.WaitGroup
		results := make(chan int, workers)
		for i := 0; i < workers; i++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				resp := ls.handleRetain(&LiteRequest{Op: "retain", AllocationIDs: []string{allocID},
					TraceID: "tr", MetricsData: metricsData, NeedReverseLookup: true})
				results <- resp.ErrorCode
			}()
		}
		wg.Wait()
		close(results)
		for code := range results {
			convey.So(code, convey.ShouldEqual, constant.InsReqSuccessCode)
		}
		convey.So(len(ls.allocations), convey.ShouldEqual, 1)
		convey.So(pool.instances["ins1"].InUse, convey.ShouldEqual, 1)
		convey.So(pool.sessions["sess1"].activeAllocs, convey.ShouldEqual, 1)
	})
}

func TestBatchRetainReacquiresMissingAllocationIndependently(t *testing.T) {
	convey.Convey("batch retain keeps hit, recovers eligible miss, and reports unrecoverable miss", t, func() {
		orig := config.GlobalConfig.LiteScheduler
		defer func() { config.GlobalConfig.LiteScheduler = orig }()
		config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{Enable: true, EnableAllTenants: true}

		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := newTestPool(t)
		ls.pools[pool.funcKey] = pool
		acquireResp := ls.handleAcquire(&LiteRequest{Op: "acquire", FuncKey: pool.funcKey,
			SessionID: "existing-session", SessionTTL: 30, Concurrency: 1, TenantID: "t1", TraceID: "tr"})
		existingID := acquireResp.ThreadID
		recoveredID := genAllocationID("recovered-session", "ins2", 8)
		failedID := genAllocationID("missing-session", "ins1", 9)
		metrics := map[string]*types.InstanceThreadMetrics{
			existingID:  {FunctionKey: pool.funcKey},
			recoveredID: newLiteReacquireMetrics(t, pool.funcKey, "recovered-session", 30),
		}
		req := &LiteRequest{Op: "batchRetain", AllocationIDs: []string{existingID, recoveredID, failedID},
			TraceID: "tr", MetricsData: marshalRetainMetrics(t, metrics), NeedReverseLookup: true}

		resp := ls.handleBatchRetain(req)
		convey.So(resp.InstanceAllocSucceed, convey.ShouldContainKey, existingID)
		convey.So(resp.InstanceAllocSucceed, convey.ShouldContainKey, recoveredID)
		convey.So(resp.InstanceAllocFailed, convey.ShouldContainKey, failedID)
		convey.So(resp.InstanceAllocFailed[failedID].ErrorCode, convey.ShouldEqual,
			statuscode.LeaseIDNotFoundCode)
		convey.So(ls.allocations, convey.ShouldContainKey, recoveredID)
		convey.So(pool.currentInUse(), convey.ShouldEqual, 2)
	})
}

func TestReleaseUnknownAllocationReturnsNotFound(t *testing.T) {
	convey.Convey("release unknown allocID -> InstanceNotFound", t, func() {
		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		relReq := &LiteRequest{Op: "release", AllocationIDs: []string{"lite:dead:ins:thread:1"}, FuncKey: "t1/fA/v1", TraceID: "tr"}
		resp := ls.handleRelease(relReq)
		convey.So(resp.ErrorCode, convey.ShouldEqual, statuscode.InstanceNotFoundErrCode)
	})
}

// TestReleaseWhenPoolNil covers HIGH2: a release that arrives after the
// function's pool has been removed (undeploy) must not dereference a nil
// pool when building the success response. The response still returns
// success with the allocID as ThreadID; only the instance fields are zero.
func TestReleaseWhenPoolNil(t *testing.T) {
	convey.Convey("release with pool==nil does not panic and returns success", t, func() {
		ls := &LiteScheduler{
			pools:       map[string]*LiteFunctionPool{}, // no pool for the funcKey
			allocations: map[string]*Allocation{},
		}
		alloc := &Allocation{
			AllocationID: "lite:hash:ins1:thread:1",
			SessionID:    "sess1", TenantID: "t1",
			InstanceID: "ins1", FuncKey: "t1/fA/v1",
			ExpireAt: time.Now().Add(liteTTL()), CreatedAt: time.Now(),
		}
		ls.allocations[alloc.AllocationID] = alloc
		relReq := &LiteRequest{Op: "release",
			AllocationIDs: []string{alloc.AllocationID}, FuncKey: "t1/fA/v1", TraceID: "tr"}
		// Must not panic.
		resp := ls.handleRelease(relReq)
		convey.So(resp.ErrorCode, convey.ShouldEqual, constant.InsReqSuccessCode)
		convey.So(resp.ThreadID, convey.ShouldEqual, alloc.AllocationID)
		convey.So(resp.InstanceID, convey.ShouldEqual, "") // slot was nil
		convey.So(ls.allocations, convey.ShouldNotContainKey, alloc.AllocationID)
	})
}

// TestConcurrentAcquireRetainNoDeadlock exercises the lock-order fix in
// HIGH1. It mixes acquire / release / retain on the same pool concurrently.
// Under the race detector this catches both data races and deadlocks (a
// deadlock would hang the test past its timeout).
func TestConcurrentAcquireRetainNoDeadlock(t *testing.T) {
	convey.Convey("concurrent acquire/release/retain does not deadlock", t, func() {
		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		ls.pools["t1/fA/v1"] = newTestPool(t)

		const n = 16
		var wg sync.WaitGroup
		wg.Add(n)
		// deadline signals timeout if any goroutine is stuck (deadlock).
		// t.Fatal must not be called from a non-test goroutine, so we capture
		// the timeout and assert on the main test goroutine after wg.Wait.
		done := make(chan struct{})
		timedOut := false
		go func() {
			select {
			case <-done:
			case <-time.After(5 * time.Second):
				timedOut = true
			}
		}()

		for i := 0; i < n; i++ {
			go func(id int) {
				defer wg.Done()
				sess := "sess" + string(rune('A'+id%8))
				req := &LiteRequest{Op: "acquire", FuncKey: "t1/fA/v1",
					SessionID: sess, SessionTTL: 30, Concurrency: 1, TenantID: "t1", TraceID: "tr"}
				resp := ls.handleAcquire(req)
				if resp.ErrorCode != constant.InsReqSuccessCode {
					return // cold-start path; nothing to retain/release
				}
				allocID := resp.ThreadID
				// retain then release in a loop to stress the lock-order paths.
				for j := 0; j < 4; j++ {
					ls.handleRetain(&LiteRequest{Op: "retain",
						AllocationIDs: []string{allocID}, TraceID: "tr"})
				}
				ls.handleRelease(&LiteRequest{Op: "release",
					AllocationIDs: []string{allocID}, FuncKey: "t1/fA/v1", TraceID: "tr"})
			}(i)
		}
		wg.Wait()
		close(done)
		if timedOut {
			t.Errorf("concurrent acquire/release/retain deadlocked")
		}
	})
}

func TestAcquireNoInstanceReturnsNoInstanceAfterTimeout(t *testing.T) {
	convey.Convey("acquire with no instances and short timeout returns NoInstanceAvailable", t, func() {
		orig := config.GlobalConfig.LiteScheduler
		defer func() { config.GlobalConfig.LiteScheduler = orig }()
		config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{Enable: true, AcquireWaitTimeoutMs: 50}
		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{},
			scaleHintSender: NewNoopSender(), stopCh: make(chan struct{})}
		pool := &LiteFunctionPool{funcKey: "t1/fA/v1", funcSpec: &types.FunctionSpecification{FuncKey: "t1/fA/v1"},
			instances: map[string]*LiteInstance{}, sessions: map[string]*sessionBinding{}, dispatcher: &concurrencyDispatcher{}}
		ls.pools["t1/fA/v1"] = pool
		req := &LiteRequest{Op: "acquire", FuncKey: "t1/fA/v1", SessionID: "sess1", Concurrency: 1, TenantID: "t1", TraceID: "tr"}
		resp := ls.handleAcquire(req)
		convey.So(resp.ErrorCode, convey.ShouldEqual, statuscode.NoInstanceAvailableErrCode)
	})
}

// TestColdStartConcurrentWithInstanceUpdateNoRace exercises the CRITICAL fix: handleColdStart
// reads pool.instances via currentInUse()/currentCapacity() (pool.RLock) while handleInstanceUpdate
// writes pool.instances under pool.Lock. Under -race this must report no fatal/no data race.
func TestColdStartConcurrentWithInstanceUpdateNoRace(t *testing.T) {
	orig := config.GlobalConfig.LiteScheduler
	defer func() { config.GlobalConfig.LiteScheduler = orig }()
	config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{Enable: true, AcquireWaitTimeoutMs: 100}
	ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{},
		scaleHintSender: NewNoopSender(), stopCh: make(chan struct{})}
	pool := &LiteFunctionPool{funcKey: "t1/fA/v1", funcSpec: &types.FunctionSpecification{FuncKey: "t1/fA/v1"},
		instances: map[string]*LiteInstance{}, sessions: map[string]*sessionBinding{}, dispatcher: &concurrencyDispatcher{}}
	ls.pools["t1/fA/v1"] = pool
	var wg sync.WaitGroup
	// N goroutines: handleAcquire (triggers cold-start, currentInUse reads map under RLock)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			req := &LiteRequest{Op: "acquire", FuncKey: "t1/fA/v1", SessionID: "sess1", Concurrency: 1, TenantID: "t1", TraceID: "tr"}
			ls.handleAcquire(req) // cold-start, no instances, times out
		}()
	}
	// M goroutines: handleInstanceUpdate (writes pool.instances under pool.Lock)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			ins := &types.Instance{InstanceID: fmt.Sprintf("ins%d", idx), FuncKey: "t1/fA/v1", ConcurrentNum: 2}
			ins.InstanceStatus.Code = int32(constant.KernelInstanceStatusRunning)
			ls.handleInstanceUpdate(pool, ins)
		}(i)
	}
	wg.Wait()
	// Under -race: no "concurrent map read/write" fatal, no data race reported.
}

// TestConcurrencyAwareReservation verifies the bind-once-reserve-many model:
// a session with Concurrency=N reserves N units at fresh bind (InUse += N),
// subsequent acquires within the session take from the reservation (InUse
// unchanged), and releases return to the reservation (InUse unchanged). The
// reservation is only released when the session unbinds.
func TestConcurrencyAwareReservation(t *testing.T) {
	convey.Convey("Concurrency=N reserves N units; subsequent acquires take from reservation", t, func() {
		orig := config.GlobalConfig.LiteScheduler
		origLeaseSpan := config.GlobalConfig.LeaseSpan
		defer func() { config.GlobalConfig.LiteScheduler = orig }()
		defer func() { config.GlobalConfig.LeaseSpan = origLeaseSpan }()
		config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{Enable: true}
		config.GlobalConfig.LeaseSpan = 5000

		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := &LiteFunctionPool{
			funcKey:    "t1/fA/v1",
			funcSpec:   &types.FunctionSpecification{FuncKey: "t1/fA/v1"},
			instances:  map[string]*LiteInstance{},
			sessions:   map[string]*sessionBinding{},
			dispatcher: &concurrencyDispatcher{},
		}
		pool.instances["ins1"] = &LiteInstance{
			InstanceID: "ins1", FuncKey: "t1/fA/v1", Capacity: 8, InUse: 0,
			Status: InstanceStatusRunning, FuncSig: "sig",
		}
		ls.pools["t1/fA/v1"] = pool

		// Acquire #1: fresh bind with Concurrency=4. Reserves 4 units on ins1.
		req := &LiteRequest{Op: "acquire", FuncKey: "t1/fA/v1",
			SessionID: "sess1", SessionTTL: 0, Concurrency: 4,
			TenantID: "t1", TraceID: "tr"}
		resp1 := ls.handleAcquire(req)
		convey.So(resp1.ErrorCode, convey.ShouldEqual, constant.InsReqSuccessCode)
		convey.So(pool.instances["ins1"].InUse, convey.ShouldEqual, 4) // reserved 4
		pool.RLock()
		binding := pool.sessions["sess1"]
		pool.RUnlock()
		convey.So(binding.reserved, convey.ShouldEqual, 3)     // 4-1 handed out
		convey.So(binding.activeAllocs, convey.ShouldEqual, 1) // 1 in-flight

		// Acquire #2 (same session): sticky hit, takes from reservation.
		resp2 := ls.handleAcquire(req)
		convey.So(resp2.InstanceID, convey.ShouldEqual, "ins1")
		convey.So(pool.instances["ins1"].InUse, convey.ShouldEqual, 4) // unchanged
		pool.RLock()
		binding = pool.sessions["sess1"]
		pool.RUnlock()
		convey.So(binding.reserved, convey.ShouldEqual, 2)
		convey.So(binding.activeAllocs, convey.ShouldEqual, 2)

		// Acquire #3 (same session): takes from reservation again.
		resp3 := ls.handleAcquire(req)
		convey.So(resp3.InstanceID, convey.ShouldEqual, "ins1")
		pool.RLock()
		binding = pool.sessions["sess1"]
		pool.RUnlock()
		convey.So(binding.reserved, convey.ShouldEqual, 1)
		convey.So(binding.activeAllocs, convey.ShouldEqual, 3)

		// Acquire #4 (same session): takes the last reserved unit.
		resp4 := ls.handleAcquire(req)
		convey.So(resp4.InstanceID, convey.ShouldEqual, "ins1")
		pool.RLock()
		binding = pool.sessions["sess1"]
		pool.RUnlock()
		convey.So(binding.reserved, convey.ShouldEqual, 0)
		convey.So(binding.activeAllocs, convey.ShouldEqual, 4)

		// Acquire #5 (same session): reservation exhausted → over-acquire (InUse++).
		resp5 := ls.handleAcquire(req)
		convey.So(resp5.InstanceID, convey.ShouldEqual, "ins1")
		convey.So(pool.instances["ins1"].InUse, convey.ShouldEqual, 5) // over-acquired 1
		pool.RLock()
		binding = pool.sessions["sess1"]
		pool.RUnlock()
		convey.So(binding.reserved, convey.ShouldEqual, 0)
		convey.So(binding.activeAllocs, convey.ShouldEqual, 5)

		// Release one: returns to reservation (InUse unchanged).
		ls.handleRelease(&LiteRequest{Op: "release",
			AllocationIDs: []string{resp5.ThreadID}, FuncKey: "t1/fA/v1", TraceID: "tr"})
		convey.So(pool.instances["ins1"].InUse, convey.ShouldEqual, 5) // unchanged
		pool.RLock()
		binding = pool.sessions["sess1"]
		pool.RUnlock()
		convey.So(binding.reserved, convey.ShouldEqual, 1) // returned to reservation
		convey.So(binding.activeAllocs, convey.ShouldEqual, 4)
	})
}

// TestConcurrencyAwareUpperBoundReject verifies that Concurrency > Capacity
// is rejected with InstanceSessionInvalidErrCode, matching concurrencyscheduler.
func TestConcurrencyAwareUpperBoundReject(t *testing.T) {
	convey.Convey("Concurrency > ConcurrentNum is rejected", t, func() {
		orig := config.GlobalConfig.LiteScheduler
		defer func() { config.GlobalConfig.LiteScheduler = orig }()
		config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{Enable: true}

		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := &LiteFunctionPool{
			funcKey: "t1/fA/v1",
			funcSpec: &types.FunctionSpecification{
				FuncKey:          "t1/fA/v1",
				InstanceMetaData: commonTypes.InstanceMetaData{ConcurrentNum: 4},
			},
			instances:  map[string]*LiteInstance{},
			sessions:   map[string]*sessionBinding{},
			dispatcher: &concurrencyDispatcher{},
		}
		pool.instances["ins1"] = &LiteInstance{
			InstanceID: "ins1", FuncKey: "t1/fA/v1", Capacity: 4, InUse: 0,
			Status: InstanceStatusRunning,
		}
		ls.pools["t1/fA/v1"] = pool

		req := &LiteRequest{Op: "acquire", FuncKey: "t1/fA/v1",
			SessionID: "sess1", Concurrency: 8, // > ConcurrentNum=4
			TenantID: "t1", TraceID: "tr"}
		resp := ls.handleAcquire(req)
		convey.So(resp.ErrorCode, convey.ShouldEqual, statuscode.InstanceSessionInvalidErrCode)
		convey.So(pool.instances["ins1"].InUse, convey.ShouldEqual, 0) // unchanged
	})
}

// TestConcurrencyAwareSessionExhaustsInstance verifies that a session with
// Concurrency=4 on a Capacity=4 instance fully reserves it, blocking other
// sessions until the first unbinds.
func TestConcurrencyAwareSessionExhaustsInstance(t *testing.T) {
	convey.Convey("full reservation blocks other sessions", t, func() {
		orig := config.GlobalConfig.LiteScheduler
		origLeaseSpan := config.GlobalConfig.LeaseSpan
		defer func() { config.GlobalConfig.LiteScheduler = orig }()
		defer func() { config.GlobalConfig.LeaseSpan = origLeaseSpan }()
		config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{Enable: true}
		config.GlobalConfig.LeaseSpan = 5000

		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := &LiteFunctionPool{
			funcKey:    "t1/fA/v1",
			funcSpec:   &types.FunctionSpecification{FuncKey: "t1/fA/v1"},
			instances:  map[string]*LiteInstance{},
			sessions:   map[string]*sessionBinding{},
			dispatcher: &concurrencyDispatcher{},
		}
		pool.instances["ins1"] = &LiteInstance{
			InstanceID: "ins1", FuncKey: "t1/fA/v1", Capacity: 4, InUse: 0,
			Status: InstanceStatusRunning, FuncSig: "sig",
		}
		ls.pools["t1/fA/v1"] = pool

		// Session A: Concurrency=4, fully reserves ins1.
		reqA := &LiteRequest{Op: "acquire", FuncKey: "t1/fA/v1",
			SessionID: "sessA", SessionTTL: 0, Concurrency: 4,
			TenantID: "t1", TraceID: "tr"}
		respA := ls.handleAcquire(reqA)
		convey.So(respA.ErrorCode, convey.ShouldEqual, constant.InsReqSuccessCode)
		convey.So(pool.instances["ins1"].InUse, convey.ShouldEqual, 4)

		// Session B: Concurrency=1, can't fit on ins1 (0 free). No other instances.
		// With AcquireWaitTimeoutMs=0, should reject immediately.
		config.GlobalConfig.LiteScheduler.AcquireWaitTimeoutMs = 0
		ls.scaleHintSender = NewNoopSender()
		ls.stopCh = make(chan struct{})
		reqB := &LiteRequest{Op: "acquire", FuncKey: "t1/fA/v1",
			SessionID: "sessB", SessionTTL: 0, Concurrency: 1,
			TenantID: "t1", TraceID: "tr"}
		respB := ls.handleAcquire(reqB)
		convey.So(respB.ErrorCode, convey.ShouldEqual, statuscode.NoInstanceAvailableErrCode)
		convey.So(pool.instances["ins1"].InUse, convey.ShouldEqual, 4) // unchanged
	})
}
