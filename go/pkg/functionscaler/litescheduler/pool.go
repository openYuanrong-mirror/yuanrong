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
}

// LiteFunctionPool holds local instances, session bindings and dispatcher for one funcKey.
type LiteFunctionPool struct {
	funcKey    string
	funcSpec   *types.FunctionSpecification
	instances  map[string]*LiteInstance
	sessions   map[string]string // sessionID -> instanceID
	dispatcher Dispatcher
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
	// Select picks one instance from slots; returns nil if none schedulable.
	Select(slots []*LiteInstance) *LiteInstance
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
	}
}

// candidateSlotsLocked returns schedulable instances; caller must hold pool.Lock.
func (p *LiteFunctionPool) candidateSlotsLocked() []*LiteInstance {
	out := make([]*LiteInstance, 0, len(p.instances))
	for _, ins := range p.instances {
		if (ins.Status == InstanceStatusRunning || ins.Status == InstanceStatusSubHealth) && ins.InUse < ins.Capacity {
			out = append(out, ins)
		}
	}
	return out
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
