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
	"testing"

	"github.com/smartystreets/goconvey/convey"
	"yuanrong.org/kernel/pkg/functionscaler/types"
)

func TestConcurrencySelectsLowestLoad(t *testing.T) {
	convey.Convey("concurrency picks lowest InUse/Capacity", t, func() {
		d := &concurrencyDispatcher{}
		slots := []*LiteInstance{
			{InstanceID: "a", Capacity: 10, InUse: 8, Status: InstanceStatusRunning},
			{InstanceID: "b", Capacity: 10, InUse: 2, Status: InstanceStatusRunning},
		}
		chosen := d.Select(slots, 1)
		convey.So(chosen.InstanceID, convey.ShouldEqual, "b")
		convey.So(d.Policy(), convey.ShouldEqual, "concurrency")
	})
}

func TestConcurrencySubHealthPenalty(t *testing.T) {
	convey.Convey("healthy preferred over subHealth even if subHealth load lower", t, func() {
		d := &concurrencyDispatcher{}
		slots := []*LiteInstance{
			{InstanceID: "h", Capacity: 10, InUse: 5, Status: InstanceStatusRunning},   // 0.5
			{InstanceID: "s", Capacity: 10, InUse: 1, Status: InstanceStatusSubHealth}, // 0.1 + 1.0 = 1.1
		}
		chosen := d.Select(slots, 1)
		convey.So(chosen.InstanceID, convey.ShouldEqual, "h")
	})
}

func TestConcurrencyNoAvailableReturnsNil(t *testing.T) {
	convey.Convey("nil when all full or unavailable", t, func() {
		d := &concurrencyDispatcher{}
		slots := []*LiteInstance{
			{InstanceID: "a", Capacity: 2, InUse: 2, Status: InstanceStatusRunning},
		}
		convey.So(d.Select(slots, 1), convey.ShouldBeNil)
	})
}

func TestRoundRobinCyclesAndPrefersHealthy(t *testing.T) {
	convey.Convey("round-robin cycles through healthy instances", t, func() {
		d := &roundRobinDispatcher{}
		slots := []*LiteInstance{
			{InstanceID: "a", Capacity: 10, InUse: 0, Status: InstanceStatusRunning},
			{InstanceID: "b", Capacity: 10, InUse: 0, Status: InstanceStatusRunning},
			{InstanceID: "c", Capacity: 10, InUse: 0, Status: InstanceStatusSubHealth},
		}
		first := d.Select(slots, 1)
		second := d.Select(slots, 1)
		convey.So(first.InstanceID, convey.ShouldEqual, "a")
		convey.So(second.InstanceID, convey.ShouldEqual, "b")
		convey.So(d.Policy(), convey.ShouldEqual, "round-robin")
	})
	convey.Convey("round-robin skips full, falls back to subHealth", t, func() {
		d := &roundRobinDispatcher{}
		slots := []*LiteInstance{
			{InstanceID: "a", Capacity: 1, InUse: 1, Status: InstanceStatusRunning}, // full
			{InstanceID: "c", Capacity: 10, InUse: 0, Status: InstanceStatusSubHealth},
		}
		chosen := d.Select(slots, 1)
		convey.So(chosen.InstanceID, convey.ShouldEqual, "c")
	})
}

func TestNewDispatcherUnknownDegradesToConcurrency(t *testing.T) {
	convey.Convey("unknown SchedulePolicy degrades to concurrency", t, func() {
		spec := &types.FunctionSpecification{}
		// InstanceMetaData.SchedulePolicy = something unknown (zero value)
		d := newDispatcher(spec)
		convey.So(d.Policy(), convey.ShouldEqual, "concurrency")
	})
}

func TestConcurrencyExcludesUnavailable(t *testing.T) {
	convey.Convey("unavailable instances are not selected", t, func() {
		d := &concurrencyDispatcher{}
		slots := []*LiteInstance{
			{InstanceID: "dead", Capacity: 10, InUse: 0, Status: InstanceStatusUnavailable},
			{InstanceID: "ok", Capacity: 10, InUse: 1, Status: InstanceStatusRunning},
		}
		// candidateSlots filters unavailable; here Select receives only ok
		chosen := d.Select([]*LiteInstance{slots[1]}, 1)
		convey.So(chosen.InstanceID, convey.ShouldEqual, "ok")
	})
}

// TestConcurrencyRespectsRequestedSize verifies that Select filters out
// instances whose remaining capacity cannot fit the requested concurrency
// (concurrency > 1), not just full instances.
func TestConcurrencyRespectsRequestedSize(t *testing.T) {
	convey.Convey("concurrency>1 filters instances with insufficient remaining capacity", t, func() {
		d := &concurrencyDispatcher{}
		slots := []*LiteInstance{
			{InstanceID: "a", Capacity: 10, InUse: 8, Status: InstanceStatusRunning}, // remaining 2
			{InstanceID: "b", Capacity: 10, InUse: 2, Status: InstanceStatusRunning},  // remaining 8
		}
		chosen := d.Select(slots, 3) // a: 2<3 skipped, b: 8>=3 picked
		convey.So(chosen.InstanceID, convey.ShouldEqual, "b")
	})
}

// TestConcurrencyInsufficientForAllReturnsNil verifies that when concurrency
// exceeds every slot's remaining capacity, Select returns nil.
func TestConcurrencyInsufficientForAllReturnsNil(t *testing.T) {
	convey.Convey("nil when concurrency exceeds all remaining capacity", t, func() {
		d := &concurrencyDispatcher{}
		slots := []*LiteInstance{
			{InstanceID: "a", Capacity: 10, InUse: 8, Status: InstanceStatusRunning}, // remaining 2
			{InstanceID: "b", Capacity: 10, InUse: 9, Status: InstanceStatusRunning},  // remaining 1
		}
		convey.So(d.Select(slots, 3), convey.ShouldBeNil)
	})
}

// TestConcurrencyZeroOrNegativeReturnsNil verifies the defensive guard at the
// Select entry: non-positive concurrency must not bypass the capacity filter
// (otherwise Capacity-InUse>=0 would be always true and pick a full instance).
func TestConcurrencyZeroOrNegativeReturnsNil(t *testing.T) {
	convey.Convey("concurrency<=0 returns nil (defensive guard)", t, func() {
		d := &concurrencyDispatcher{}
		slots := []*LiteInstance{
			{InstanceID: "a", Capacity: 10, InUse: 0, Status: InstanceStatusRunning},
		}
		convey.So(d.Select(slots, 0), convey.ShouldBeNil)
		convey.So(d.Select(slots, -1), convey.ShouldBeNil)
	})
}

// TestRoundRobinSkipsInsufficientCapacity verifies that roundRobin skips
// instances whose remaining capacity cannot fit the requested concurrency.
func TestRoundRobinSkipsInsufficientCapacity(t *testing.T) {
	convey.Convey("round-robin skips instances that cannot fit concurrency", t, func() {
		d := &roundRobinDispatcher{}
		slots := []*LiteInstance{
			{InstanceID: "a", Capacity: 2, InUse: 1, Status: InstanceStatusRunning},  // remaining 1
			{InstanceID: "b", Capacity: 10, InUse: 0, Status: InstanceStatusRunning}, // remaining 10
		}
		chosen := d.Select(slots, 2) // a: 1<2 skipped, b: 10>=2 picked
		convey.So(chosen.InstanceID, convey.ShouldEqual, "b")
	})
}
