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
	"math"
	"sync"

	"yuanrong.org/kernel/pkg/functionscaler/types"
)

// concurrencyDispatcher selects the instance with lowest InUse/Capacity score.
type concurrencyDispatcher struct{}

// Select picks the slot with the lowest InUse/Capacity score. Returns nil when no
// slot has remaining capacity. slots must be a consistent snapshot; reads of
// ins.InUse/ins.Status are not locked.
func (d *concurrencyDispatcher) Select(slots []*LiteInstance) *LiteInstance {
	var best *LiteInstance
	bestScore := math.MaxFloat64
	for _, ins := range slots {
		if ins.Capacity <= 0 || ins.InUse >= ins.Capacity {
			continue
		}
		score := float64(ins.InUse) / float64(ins.Capacity)
		if ins.Status == InstanceStatusSubHealth {
			score += subHealthPenalty
		}
		if score < bestScore {
			bestScore = score
			best = ins
		}
	}
	return best
}
func (d *concurrencyDispatcher) Policy() string { return types.InstanceSchedulePolicyConcurrency }

// roundRobinDispatcher cycles a cursor through healthy instances, falling back to subHealth.
//
// Contract: callers must pass slots in a stable order across calls (e.g. sorted by
// InstanceID) so that curIndex advances round-robin. Instance add/remove events may
// briefly perturb the cursor; this is acceptable since add/remove is rare.
// slots must be a consistent snapshot; reads of ins.InUse/ins.Status are not locked.
type roundRobinDispatcher struct {
	curIndex int
	mu       sync.Mutex
}

// Select advances the round-robin cursor across slots, preferring Running instances
// and falling back to SubHealth. Returns nil when no slot has remaining capacity.
func (d *roundRobinDispatcher) Select(slots []*LiteInstance) *LiteInstance {
	d.mu.Lock()
	defer d.mu.Unlock()
	n := len(slots)
	if n == 0 {
		return nil
	}
	if d.curIndex >= n {
		d.curIndex %= n
	}
	for offset := 0; offset < n; offset++ {
		idx := (d.curIndex + offset) % n
		ins := slots[idx]
		if ins.Status == InstanceStatusRunning && ins.InUse < ins.Capacity {
			d.curIndex = (idx + 1) % n
			return ins
		}
	}
	for offset := 0; offset < n; offset++ {
		idx := (d.curIndex + offset) % n
		ins := slots[idx]
		if ins.Status == InstanceStatusSubHealth && ins.InUse < ins.Capacity {
			d.curIndex = (idx + 1) % n
			return ins
		}
	}
	return nil
}
func (d *roundRobinDispatcher) Policy() string { return types.InstanceSchedulePolicyRoundRobin }

// newDispatcher picks a dispatcher by funcSpec.SchedulePolicy; unknown degrades to concurrency.
func newDispatcher(funcSpec *types.FunctionSpecification) Dispatcher {
	if funcSpec == nil || funcSpec.InstanceMetaData.SchedulePolicy == "" {
		return &concurrencyDispatcher{}
	}
	switch funcSpec.InstanceMetaData.SchedulePolicy {
	case types.InstanceSchedulePolicyRoundRobin:
		return &roundRobinDispatcher{}
	default:
		return &concurrencyDispatcher{}
	}
}
