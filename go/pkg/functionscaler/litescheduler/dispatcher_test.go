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
		chosen := d.Select(slots)
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
		chosen := d.Select(slots)
		convey.So(chosen.InstanceID, convey.ShouldEqual, "h")
	})
}

func TestConcurrencyNoAvailableReturnsNil(t *testing.T) {
	convey.Convey("nil when all full or unavailable", t, func() {
		d := &concurrencyDispatcher{}
		slots := []*LiteInstance{
			{InstanceID: "a", Capacity: 2, InUse: 2, Status: InstanceStatusRunning},
		}
		convey.So(d.Select(slots), convey.ShouldBeNil)
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
		first := d.Select(slots)
		second := d.Select(slots)
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
		chosen := d.Select(slots)
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
		chosen := d.Select([]*LiteInstance{slots[1]})
		convey.So(chosen.InstanceID, convey.ShouldEqual, "ok")
	})
}
