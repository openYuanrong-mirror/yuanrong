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
	"sync"
	"time"

	"yuanrong.org/kernel/pkg/common/faas_common/constant"
	"yuanrong.org/kernel/pkg/functionscaler/types"
)

// InstanceStatus is the scheduling status of a local instance slot.
type InstanceStatus int

const (
	// InstanceStatusUnavailable covers fatal/evicted/exiting/deleted/new/scheduling/creating.
	InstanceStatusUnavailable InstanceStatus = iota
	// InstanceStatusRunning is schedulable, highest priority.
	InstanceStatusRunning
	// InstanceStatusSubHealth is schedulable but lower priority.
	InstanceStatusSubHealth
)

// subHealthPenalty makes subHealth rank below healthy even when its load is lower.
const subHealthPenalty = 1.0

// LiteInstance is a local slot view of an instance for LiteScheduler dispatch.
type LiteInstance struct {
	InstanceID      string
	FuncKey         string
	Capacity        int
	InUse           int
	Status          InstanceStatus
	InstanceIP      string
	InstancePort    string
	NodeIP          string
	NodePort        string
	FuncSig         string
	FunctionProxyID string
	RouteAddress    string
	AZ              string
	SessionCtxID    string
	IdleSince       time.Time
	Reclaiming      bool
}

// sessionBinding tracks a session's binding to an instance plus the idle-unbind
// timer state. It mirrors legacy's sessionRecord: when activeAllocs drops to 0,
// a timer is started; if a new acquire arrives before the timer fires, the timer
// is cancelled. On timer fire, the session→instance binding is removed.
//
// Concurrency-aware reservation model (matches concurrencyscheduler's
// bind-once-reserve-many): at fresh bind, slot.InUse is bumped by the session's
// Concurrency; reserved holds units not yet handed out to in-flight acquires;
// activeAllocs holds units currently handed out. Subsequent acquires within the
// session decrement reserved (no slot.InUse change); releases return to reserved.
// The reservation is released back to the instance only when the session unbinds
// (idle-unbind timer, instance removal, pool deletion).
type sessionBinding struct {
	instanceID   string
	reserved     int // capacity units reserved on the instance, not yet handed out
	activeAllocs int // outstanding allocations handed out from the reservation (incl. over-acquire)
	timer        *time.Timer
	expiring     bool // true when the idle-unbind timer is ticking
}

// LiteFunctionPool holds local instances, session bindings and dispatcher for one funcKey.
type LiteFunctionPool struct {
	funcKey      string
	funcSpec     *types.FunctionSpecification
	instances    map[string]*LiteInstance
	sessions     map[string]*sessionBinding // sessionID -> binding
	dispatcher   Dispatcher
	sessionStore *liteSessionStore // external store coordinator; nil => all ops no-op (tests)
	sync.RWMutex
	seqCounter uint64 // for allocationID seq; protected by pool.Lock (writer-serialized)
}

// PoolStats is a read-only snapshot for Prometheus collector.
type PoolStats struct {
	FuncKey       string
	TenantID      string
	InstanceCount int
	Capacity      int
	InUse         int
	SessionCount  int
	Policy        string
}

// Dispatcher selects a target LiteInstance for a session request.
type Dispatcher interface {
	// Select picks one instance from slots that can fit the requested concurrency;
	// returns nil if none schedulable. slots must be a consistent snapshot; reads
	// of ins.InUse/ins.Status are not locked.
	Select(slots []*LiteInstance, concurrency int) *LiteInstance
	// Policy returns the dispatcher policy name.
	Policy() string
}

// mapStatus maps instance.InstanceStatus.Code to LiteInstance.Status.
func mapStatus(code int32) InstanceStatus {
	switch code {
	case int32(constant.KernelInstanceStatusRunning):
		return InstanceStatusRunning
	case int32(constant.KernelInstanceStatusSubHealth):
		return InstanceStatusSubHealth
	default:
		return InstanceStatusUnavailable
	}
}

// buildLiteInstanceFromInstance copies schedulable fields from types.Instance.
func buildLiteInstanceFromInstance(ins *types.Instance) *LiteInstance {
	if ins == nil {
		return nil
	}
	return &LiteInstance{
		InstanceID:      ins.InstanceID,
		FuncKey:         ins.FuncKey,
		Capacity:        ins.ConcurrentNum,
		Status:          mapStatus(ins.InstanceStatus.Code),
		InstanceIP:      ins.InstanceIP,
		InstancePort:    ins.InstancePort,
		NodeIP:          ins.NodeIP,
		NodePort:        ins.NodePort,
		FuncSig:         ins.FuncSig,
		FunctionProxyID: ins.FunctionProxyID,
		RouteAddress:    ins.RouteAddress,
		AZ:              ins.AZ,
		SessionCtxID:    instanceSessionCtxID(ins),
	}
}

// candidateSlotsLocked returns schedulable instances that can fit the requested
// concurrency; caller must hold pool.Lock.
func (p *LiteFunctionPool) candidateSlotsLocked(sessionCtxID string, concurrency int) []*LiteInstance {
	out := make([]*LiteInstance, 0, len(p.instances))
	for _, ins := range p.instances {
		if ins.SessionCtxID == sessionCtxID && !ins.Reclaiming &&
			(ins.Status == InstanceStatusRunning || ins.Status == InstanceStatusSubHealth) &&
			ins.Capacity-ins.InUse >= concurrency {
			out = append(out, ins)
		}
	}
	return out
}

func instanceSessionCtxID(ins *types.Instance) string {
	if ins == nil || ins.SessionCtxID == nil {
		return ""
	}
	return *ins.SessionCtxID
}

func (p *LiteFunctionPool) sessionBindingKey(sessionID, sessionCtxID string) string {
	if p == nil || p.funcSpec == nil || !p.funcSpec.ExtendedMetaData.EnableSessionCtx {
		return sessionID
	}
	return types.JoinKey(sessionID, sessionCtxID)
}

// instanceConcurrentNum returns the per-instance concurrency limit configured on
// the funcSpec (0 means unset, i.e. no limit). It takes pool.RLock itself, so the
// caller must NOT hold pool.Lock (or pool.RLock): upsertPool swaps the funcSpec
// pointer under pool.Lock, and reading it unlocked would race with the swap.
func (p *LiteFunctionPool) instanceConcurrentNum() int {
	p.RLock()
	defer p.RUnlock()
	if p.funcSpec == nil {
		return 0
	}
	return p.funcSpec.InstanceMetaData.ConcurrentNum
}

// currentInUse returns the sum of InUse over all instances. It takes pool.RLock itself,
// so the caller must NOT hold pool.Lock (or pool.RLock). handleColdStart invokes this for
// the ScaleHint snapshot AFTER handleAcquire has released pool.Lock, so the RLock here is
// not nested with any caller-held lock and cannot deadlock. The RLock is mutually exclusive
// with event.go's pool.Lock writers (handleInstanceUpdate writes pool.instances), so the
// map read here is safe against concurrent writes.
func (p *LiteFunctionPool) currentInUse() int {
	p.RLock()
	defer p.RUnlock()
	n := 0
	for _, ins := range p.instances {
		n += ins.InUse
	}
	return n
}

// currentCapacity returns the sum of Capacity over all instances. See currentInUse for
// the locking contract: caller must NOT hold pool.Lock; this takes pool.RLock itself.
func (p *LiteFunctionPool) currentCapacity() int {
	p.RLock()
	defer p.RUnlock()
	n := 0
	for _, ins := range p.instances {
		n += ins.Capacity
	}
	return n
}

// instanceByID returns the instance pointer for id (nil if absent); caller manages locking.
func (p *LiteFunctionPool) instanceByID(id string) *LiteInstance { return p.instances[id] }

// Stats returns a read-only snapshot of pool state for the Prometheus collector.
// Only Running/SubHealth instances contribute to Capacity/InUse/InstanceCount,
// matching candidateSlotsLocked's schedulable definition (without the InUse<Capacity
// filter, since capacity reporting should include full instances too).
func (p *LiteFunctionPool) Stats() PoolStats {
	p.RLock()
	defer p.RUnlock()
	var capacity, inUse, instCount int
	for _, ins := range p.instances {
		if ins.Status == InstanceStatusRunning || ins.Status == InstanceStatusSubHealth {
			instCount++
			capacity += ins.Capacity
			inUse += ins.InUse
		}
	}
	policy := "unknown"
	if p.dispatcher != nil {
		policy = p.dispatcher.Policy()
	}
	return PoolStats{
		FuncKey:       p.funcKey,
		TenantID:      splitFuncKey(p.funcKey).tenantID,
		InstanceCount: instCount,
		Capacity:      capacity,
		InUse:         inUse,
		SessionCount:  len(p.sessions),
		Policy:        policy,
	}
}

// sessionTTLFor normalizes a request-provided sessionTTL (seconds) to a Duration.
// 0 means immediate unbind (timer fires instantly); positive values are used as-is.
// Negative values are rejected by handleAcquire before reaching here.
func sessionTTLFor(reqTTL int) time.Duration {
	if reqTTL <= 0 {
		return 0
	}
	return time.Duration(reqTTL) * time.Second
}

// tryLocalStickyLocked checks the local session binding and returns the matching
// schedulable slot and its binding. Returns (slot, binding, true) on sticky hit
// (and cancels any pending idle-unbind timer). A sticky hit requires either a
// non-empty reservation (reserved>0, can hand out without touching instance
// capacity) OR remaining instance capacity (InUse<Capacity, can over-acquire).
// Returns (nil, nil, false) on miss or on an invalidated binding (instance
// absent/unhealthy/full); in the latter case the stale binding is removed so
// the caller can dispatch or lazily recover from the external store.
// Shared by handleAcquire Phase 1 (first lookup) and Phase 3 (re-check after the
// out-of-lock store.Get). Caller must hold pool.Lock.
func (p *LiteFunctionPool) tryLocalStickyLocked(bindingKey string) (*LiteInstance, *sessionBinding, bool) {
	binding, ok := p.sessions[bindingKey]
	if !ok {
		return nil, nil, false
	}
	slot := p.instances[binding.instanceID]
	if slot != nil &&
		(slot.Status == InstanceStatusRunning || slot.Status == InstanceStatusSubHealth) &&
		(binding.reserved > 0 || slot.InUse < slot.Capacity) {
		p.cancelSessionUnbind(bindingKey)
		return slot, binding, true
	}
	// Binding exists but its instance is absent/unhealthy/full: clean the stale
	// binding so dispatch/recovery start from a clean slate. removeSessionBinding
	// also releases any reservation the binding still held back to the instance.
	p.removeSessionBinding(bindingKey)
	return nil, nil, false
}

// bindSessionFreshLocked creates a new sessionBinding that reserves `concurrency`
// capacity units on the instance. The caller must have already bumped slot.InUse
// by concurrency. The binding starts with reserved=concurrency-1 (one unit is
// immediately handed out to the in-flight acquire) and activeAllocs=1. If a stale
// binding for the same key somehow exists (defensive; tryLocalStickyLocked should
// have removed it), its pending timer is stopped and it is overwritten.
// Caller must hold pool.Lock.
func (p *LiteFunctionPool) bindSessionFreshLocked(bindingKey, instanceID string, concurrency int) {
	binding := &sessionBinding{
		instanceID:   instanceID,
		reserved:     concurrency - 1,
		activeAllocs: 1,
	}
	if old, ok := p.sessions[bindingKey]; ok {
		old.stopTimer()
	}
	p.sessions[bindingKey] = binding
}

// bindSessionStickyTakeLocked hands out one unit from an existing binding's
// reservation. If the reservation is exhausted (reserved==0), the unit is
// over-acquired directly from the instance (caller bumps slot.InUse by 1).
// Returns the slot.InUse delta the caller must apply: 0 when taken from
// reserved, 1 when over-acquired. Caller must hold pool.Lock.
func (p *LiteFunctionPool) bindSessionStickyTakeLocked(binding *sessionBinding) int {
	if binding.reserved > 0 {
		binding.reserved--
		binding.activeAllocs++
		return 0
	}
	// over-acquire: reservation exhausted, take one more unit from the instance
	binding.activeAllocs++
	return 1
}

// unbindSessionOnRelease decrements activeAllocs and returns the released unit
// to the session's reservation pool (reserved++), NOT to the instance. The
// instance capacity reserved by this session is only released when the session
// unbinds (removeSessionBinding). If activeAllocs reaches 0 and no idle-unbind
// timer is running, one is started. The caller schedules the timer outside
// pool.Lock. Caller must hold pool.Lock.
func (p *LiteFunctionPool) unbindSessionOnRelease(sessionID string) (needTimer bool, ttl time.Duration) {
	binding, ok := p.sessions[sessionID]
	if !ok {
		return false, 0
	}
	if binding.activeAllocs > 0 {
		binding.activeAllocs--
		binding.reserved++ // return to session's reservation pool, not to the instance
	}
	if binding.activeAllocs > 0 || binding.expiring {
		return false, 0
	}
	// All allocations released and no timer running: start idle-unbind countdown.
	binding.expiring = true
	return true, 0 // ttl filled by caller via sessionTTLFor
}

// cancelSessionUnbind cancels the idle-unbind timer if it is running.
// Called when an acquire arrives for a session whose timer is ticking.
// Caller must hold pool.Lock.
func (p *LiteFunctionPool) cancelSessionUnbind(sessionID string) {
	binding, ok := p.sessions[sessionID]
	if !ok || !binding.expiring {
		return
	}
	binding.stopTimer()
	binding.expiring = false
}

// removeSessionBinding deletes the session binding entry entirely and releases
// the session's reserved capacity (reserved+activeAllocs) back to the instance.
// It enqueues an async Delete of the external store record so a subsequent
// acquire on the same session does not recover a stale binding. Used by the
// timer callback, instance deletion cleanup and sticky-invalidated re-dispatch.
// Caller must hold pool.Lock; the async enqueue does not block on I/O. nil-safe
// when sessionStore is unset. deletePool does NOT call this (it bulk-syncs via
// cleanExternalRecords instead); the instance may already be gone (removed by
// the caller before this runs), in which case the reservation release is a no-op.
func (p *LiteFunctionPool) removeSessionBinding(sessionID string) {
	if binding, ok := p.sessions[sessionID]; ok {
		binding.stopTimer()
		// Release the session's reservation back to the instance. The instance
		// may already be deleted (removeInstanceLocked deletes the map entry
		// before iterating sessions), in which case slot is nil and the release
		// is a no-op — the instance's InUse no longer matters.
		p.processInstanceInUse(binding)
	}
	delete(p.sessions, sessionID)
	p.sessionStore.deleteSessionFromStore(sessionID)
}

func (p *LiteFunctionPool) processInstanceInUse(binding *sessionBinding) {
	if slot := p.instances[binding.instanceID]; slot != nil {
		held := binding.reserved + binding.activeAllocs
		if held > 0 {
			if slot.InUse >= held {
				slot.InUse -= held
			} else {
				slot.InUse = 0 // defensive: should not happen
			}
		}
	}
}

// stopTimer stops the timer if set; safe to call when timer is nil.
func (b *sessionBinding) stopTimer() {
	if b.timer != nil {
		b.timer.Stop()
		b.timer = nil
	}
}
