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
	"strings"
	"testing"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/smartystreets/goconvey/convey"
	"yuanrong.org/kernel/pkg/functionscaler/types"
)

func TestLiteCollectorDescribeCollect(t *testing.T) {
	convey.Convey("collector registers and scrapes", t, func() {
		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		pool := &LiteFunctionPool{funcKey: "t1/fA/v1", instances: map[string]*LiteInstance{}, sessions: map[string]*sessionBinding{}, dispatcher: &concurrencyDispatcher{}}
		pool.instances["ins1"] = &LiteInstance{InstanceID: "ins1", Capacity: 2, InUse: 1, Status: InstanceStatusRunning, FuncKey: "t1/fA/v1"}
		ls.pools["t1/fA/v1"] = pool
		c := NewLiteCollector(ls)
		// Collect should not panic and should emit metrics
		ch := make(chan prometheus.Metric, 64)
		c.Collect(ch)
		convey.So(len(ch), convey.ShouldBeGreaterThan, 0)
	})
}

// TestLiteCollectorIncAcquireWired verifies the acquire counter is incremented by
// the acquire path (assignInstance), proving metrics are wired rather than stuck at 0.
func TestLiteCollectorIncAcquireWired(t *testing.T) {
	convey.Convey("acquire increments the faas_lite_acquire_total counter", t, func() {
		ls := &LiteScheduler{pools: map[string]*LiteFunctionPool{}, allocations: map[string]*Allocation{}}
		ls.metrics = NewLiteCollector(ls)
		pool := &LiteFunctionPool{funcKey: "t1/fA/v1", funcSpec: &types.FunctionSpecification{FuncKey: "t1/fA/v1"},
			instances: map[string]*LiteInstance{}, sessions: map[string]*sessionBinding{}, dispatcher: &concurrencyDispatcher{}}
		pool.instances["ins1"] = &LiteInstance{InstanceID: "ins1", FuncKey: "t1/fA/v1", Capacity: 2, InUse: 0,
			Status: InstanceStatusRunning, FuncSig: "sig"}
		ls.pools["t1/fA/v1"] = pool
		req := &LiteRequest{Op: "acquire", FuncKey: "t1/fA/v1", SessionID: "sess1", TenantID: "t1", TraceID: "tr"}
		resp := ls.handleAcquire(req, time.Now())
		convey.So(resp.ErrorCode, convey.ShouldEqual, 6030) // constant.InsReqSuccessCode

		ch := make(chan prometheus.Metric, 128)
		ls.metrics.Collect(ch)
		close(ch)
		foundAcquire := false
		for m := range ch {
			if strings.Contains(m.Desc().String(), liteMetricAcquire) {
				foundAcquire = true
			}
		}
		convey.So(foundAcquire, convey.ShouldBeTrue)
	})
}
