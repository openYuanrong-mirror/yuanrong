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
	"yuanrong.org/kernel/pkg/common/faas_common/constant"
	"yuanrong.org/kernel/pkg/functionscaler/types"
)

func TestHandleInstanceUpdateRunningAddsSlot(t *testing.T) {
	convey.Convey("running instance added to pool", t, func() {
		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := &LiteFunctionPool{funcKey: "t1/fA/v1", funcSpec: &types.FunctionSpecification{FuncKey: "t1/fA/v1"},
			instances: map[string]*LiteInstance{}, sessions: map[string]string{}, dispatcher: &concurrencyDispatcher{}}
		ls.pools["t1/fA/v1"] = pool
		ins := &types.Instance{InstanceID: "ins1", FuncKey: "t1/fA/v1", ConcurrentNum: 5}
		ins.InstanceStatus.Code = int32(constant.KernelInstanceStatusRunning)
		ls.handleInstanceUpdate(pool, ins)
		convey.So(pool.instances["ins1"], convey.ShouldNotBeNil)
		convey.So(pool.instances["ins1"].Status, convey.ShouldEqual, InstanceStatusRunning)
	})
}

func TestHandleInstanceUpdateFatalRemovesSlot(t *testing.T) {
	convey.Convey("fatal instance removed, allocation/session cleaned", t, func() {
		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := &LiteFunctionPool{funcKey: "t1/fA/v1", funcSpec: &types.FunctionSpecification{FuncKey: "t1/fA/v1"},
			instances: map[string]*LiteInstance{}, sessions: map[string]string{}, dispatcher: &concurrencyDispatcher{}}
		pool.instances["ins1"] = &LiteInstance{InstanceID: "ins1", Capacity: 2, InUse: 1, Status: InstanceStatusRunning}
		pool.sessions["sess1"] = "ins1"
		ls.pools["t1/fA/v1"] = pool
		ls.allocations["lite:x:ins1:thread:1"] = &Allocation{AllocationID: "lite:x:ins1:thread:1", SessionID: "sess1", InstanceID: "ins1", FuncKey: "t1/fA/v1"}
		ins := &types.Instance{InstanceID: "ins1", FuncKey: "t1/fA/v1"}
		ins.InstanceStatus.Code = int32(constant.KernelInstanceStatusFatal)
		ls.handleInstanceUpdate(pool, ins)
		convey.So(pool.instances["ins1"], convey.ShouldBeNil)
		convey.So(pool.sessions, convey.ShouldNotContainKey, "sess1")
		convey.So(ls.allocations["lite:x:ins1:thread:1"], convey.ShouldBeNil)
	})
}

func TestFunctionDeleteRemovesPool(t *testing.T) {
	convey.Convey("function delete removes pool and allocations", t, func() {
		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		ls.pools["t1/fA/v1"] = &LiteFunctionPool{funcKey: "t1/fA/v1", instances: map[string]*LiteInstance{}, sessions: map[string]string{}}
		ls.allocations["lite:x:ins1:thread:1"] = &Allocation{FuncKey: "t1/fA/v1"}
		ls.deletePool("t1/fA/v1")
		convey.So(ls.pools["t1/fA/v1"], convey.ShouldBeNil)
		convey.So(ls.allocations["lite:x:ins1:thread:1"], convey.ShouldBeNil)
	})
}
