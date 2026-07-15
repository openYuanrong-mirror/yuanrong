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
	"time"

	"github.com/smartystreets/goconvey/convey"
	"yuanrong.org/kernel/pkg/functionscaler/config"
	"yuanrong.org/kernel/pkg/functionscaler/types"
)

func TestIsFuncEnabled(t *testing.T) {
	orig := config.GlobalConfig.LiteScheduler
	defer func() { config.GlobalConfig.LiteScheduler = orig }()

	convey.Convey("enable=false -> always false", t, func() {
		config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{Enable: false}
		ls := &LiteScheduler{}
		convey.So(ls.isFuncEnabled("t1/f/v1"), convey.ShouldBeFalse)
	})
	convey.Convey("enable + enableAllTenants -> true", t, func() {
		config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{
			Enable: true, EnableAllTenants: true,
		}
		ls := &LiteScheduler{}
		convey.So(ls.isFuncEnabled("t1/f/v1"), convey.ShouldBeTrue)
	})
	convey.Convey("enable + tenant whitelist hit", t, func() {
		config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{
			Enable:         true,
			EnabledTenants: []string{"t1"},
		}
		ls := &LiteScheduler{}
		convey.So(ls.isFuncEnabled("t1/f/v1"), convey.ShouldBeTrue)
		convey.So(ls.isFuncEnabled("t2/f/v1"), convey.ShouldBeFalse)
	})
	convey.Convey("enable + func whitelist hit", t, func() {
		config.GlobalConfig.LiteScheduler = types.LiteSchedulerConfig{
			Enable:           true,
			EnabledFunctions: []string{"t1/fA/v1"},
		}
		ls := &LiteScheduler{}
		convey.So(ls.isFuncEnabled("t1/fA/v1"), convey.ShouldBeTrue)
		convey.So(ls.isFuncEnabled("t1/fB/v1"), convey.ShouldBeFalse)
	})
}

func TestProcessReverseLookupFillsSessionID(t *testing.T) {
	convey.Convey("release reverse lookup fills sessionID from allocation", t, func() {
		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := newTestPool(t) // helper from operation_test (same package)
		ls.pools["t1/fA/v1"] = pool
		// acquire first to create allocation
		acqReq := &LiteRequest{Op: "acquire", FuncKey: "t1/fA/v1", SessionID: "sess1", TenantID: "t1", TraceID: "tr"}
		resp := ls.handleAcquire(acqReq, time.Now())
		allocID := resp.ThreadID
		// release via Process with only allocID (no sessionID)
		relReq := &LiteRequest{Op: "release", AllocationIDs: []string{allocID}, NeedReverseLookup: true, TraceID: "tr"}
		err := ls.processRequest(relReq, "", nil)
		convey.So(err, convey.ShouldBeNil)
	})
}
