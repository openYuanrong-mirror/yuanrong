/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
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

// Package scaler -
package scaler

import (
	"testing"
	"time"

	"github.com/agiledragon/gomonkey/v2"
	"github.com/smartystreets/goconvey/convey"
	"github.com/stretchr/testify/assert"

	"yuanrong.org/kernel/pkg/functionscaler/metrics"
)

func TestAutoScaler_TriggerScale(t *testing.T) {
	as := &AutoScaler{
		autoScaleUpFlag:  false,
		scaleUpTriggerCh: make(chan struct{}, 1),
	}
	as.TriggerScale(0)
	assert.Equal(t, true, as.autoScaleUpFlag)
	assert.Equal(t, 0, as.minScaleDemand)
}

func TestAutoScaler_TriggerScaleWithMinDemand(t *testing.T) {
	as := &AutoScaler{
		autoScaleUpFlag:  false,
		scaleUpTriggerCh: make(chan struct{}, 1),
	}
	as.TriggerScale(2)
	assert.Equal(t, true, as.autoScaleUpFlag)
	assert.Equal(t, 2, as.minScaleDemand)
	// a smaller demand must not lower the recorded minimum, a larger one raises it
	as.TriggerScale(1)
	assert.Equal(t, 2, as.minScaleDemand)
	as.TriggerScale(3)
	assert.Equal(t, 3, as.minScaleDemand)
}

func TestAutoScaler_scaleUpInstancesWithMinDemand(t *testing.T) {
	convey.Convey("hint demand drives scale up when legacy queue is empty", t, func() {
		scaleInsNum := 0
		as := &AutoScaler{
			concurrentNum:    1,
			metricsCollector: metrics.NewBucketMetricsCollector("f", "r"),
			checkReqNumFunc:  func() int { return 0 },
			minScaleDemand:   1,
			scaleUpHandler: func(num int, _ ScaleUpCallback) {
				scaleInsNum = num
			},
		}
		as.scaleUpInstances()
		convey.So(scaleInsNum, convey.ShouldEqual, 1)
		convey.So(as.minScaleDemand, convey.ShouldEqual, 0)
		convey.So(as.pendingInsThdNum, convey.ShouldEqual, 1)
	})
	convey.Convey("demand already covered by pending instances scales nothing more", t, func() {
		scaleInsNum := -1
		as := &AutoScaler{
			concurrentNum:    1,
			metricsCollector: metrics.NewBucketMetricsCollector("f", "r"),
			checkReqNumFunc:  func() int { return 0 },
			minScaleDemand:   1,
			pendingInsThdNum: 1,
			scaleUpHandler: func(num int, _ ScaleUpCallback) {
				scaleInsNum = num
			},
		}
		as.scaleUpInstances()
		convey.So(scaleInsNum, convey.ShouldEqual, 0)
		convey.So(as.minScaleDemand, convey.ShouldEqual, 0)
	})
}

func TestAutoScaler_UpdateCreateMetrics(t *testing.T) {
	as := &AutoScaler{}
	as.UpdateCreateMetrics(5 * time.Second)
	assert.Equal(t, 5*time.Second, as.coldStartTime)
}

func TestAutoScaler_scaleUpLoop(t *testing.T) {
	as := &AutoScaler{}
	convey.Convey("channel close", t, func() {
		as.scaleUpTriggerCh = make(chan struct{}, 1)
		as.stopCh = make(chan struct{}, 1)
		close(as.scaleUpTriggerCh)
		as.scaleUpLoop()
		as.scaleUpTriggerCh = make(chan struct{}, 1)
		close(as.stopCh)
		as.scaleUpLoop()
	})
	convey.Convey("normal case", t, func() {
		reqNum := 1
		as.checkReqNumFunc = func() int { return reqNum }
		as.scaleUpTriggerCh = make(chan struct{}, 1)
		as.stopCh = make(chan struct{}, 1)
		as.scaleUpWindow = 50 * time.Millisecond
		callCount := 0
		p := gomonkey.ApplyFunc((*AutoScaler).scaleUpInstances, func() {
			callCount++
			reqNum = 0
		})
		go as.scaleUpLoop()
		time.Sleep(100 * time.Millisecond)
		as.scaleUpTriggerCh <- struct{}{}
		time.Sleep(200 * time.Millisecond)
		convey.So(as.autoScaleUpFlag, convey.ShouldBeFalse)
		convey.So(callCount, convey.ShouldEqual, 1)
		p.Reset()
		close(as.stopCh)
	})
	convey.Convey("hint demand keeps scale up loop from pausing on empty queue", t, func() {
		as.checkReqNumFunc = func() int { return 0 }
		as.minScaleDemand = 1
		as.scaleUpTriggerCh = make(chan struct{}, 1)
		as.stopCh = make(chan struct{}, 1)
		as.scaleUpWindow = 50 * time.Millisecond
		callCount := 0
		p := gomonkey.ApplyFunc((*AutoScaler).scaleUpInstances, func() {
			callCount++
			as.minScaleDemand = 0
		})
		go as.scaleUpLoop()
		time.Sleep(100 * time.Millisecond)
		as.scaleUpTriggerCh <- struct{}{}
		time.Sleep(200 * time.Millisecond)
		convey.So(callCount, convey.ShouldEqual, 1)
		convey.So(as.autoScaleUpFlag, convey.ShouldBeFalse)
		p.Reset()
		close(as.stopCh)
	})
}

func TestAutoScaler_scaleDownLoop(t *testing.T) {
	as := &AutoScaler{}
	convey.Convey("channel close", t, func() {
		as.scaleDownTriggerCh = make(chan struct{}, 1)
		as.stopCh = make(chan struct{}, 1)
		close(as.scaleDownTriggerCh)
		as.scaleDownLoop()
		as.scaleDownTriggerCh = make(chan struct{}, 1)
		close(as.stopCh)
		as.scaleDownLoop()
	})
	convey.Convey("normal case", t, func() {
		as.scaleDownTriggerCh = make(chan struct{}, 1)
		as.stopCh = make(chan struct{}, 1)
		as.scaleDownWindow = 50 * time.Millisecond
		callCount := 0
		p := gomonkey.ApplyFunc((*AutoScaler).scaleDownInstances, func() {
			callCount++
		})
		go as.scaleDownLoop()
		time.Sleep(100 * time.Millisecond)
		as.scaleDownTriggerCh <- struct{}{}
		time.Sleep(200 * time.Millisecond)
		convey.So(as.autoScaleDownFlag, convey.ShouldBeFalse)
		convey.So(callCount, convey.ShouldEqual, 1)
		p.Reset()
		close(as.stopCh)
	})
}

func TestAutoScaler_pendingInsNumOperation(t *testing.T) {
	as := &AutoScaler{concurrentNum: 100}
	convey.Convey("increase", t, func() {
		as.handlePendingInsNumIncrease(1)
		convey.So(as.pendingInsThdNum, convey.ShouldEqual, 100)
	})
	convey.Convey("decrease", t, func() {
		as.handlePendingInsNumDecrease(1)
		convey.So(as.pendingInsThdNum, convey.ShouldEqual, 0)
	})
}
