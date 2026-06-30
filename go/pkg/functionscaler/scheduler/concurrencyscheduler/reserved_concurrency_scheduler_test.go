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

// Package concurrencyscheduler -
package concurrencyscheduler

import (
	"errors"
	"reflect"
	"testing"
	"time"

	"github.com/agiledragon/gomonkey/v2"
	"github.com/stretchr/testify/assert"

	"yuanrong.org/kernel/pkg/common/faas_common/constant"
	"yuanrong.org/kernel/pkg/common/faas_common/resspeckey"
	"yuanrong.org/kernel/pkg/common/faas_common/snerror"
	commontypes "yuanrong.org/kernel/pkg/common/faas_common/types"
	"yuanrong.org/kernel/pkg/functionscaler/config"
	"yuanrong.org/kernel/pkg/functionscaler/lease"
	"yuanrong.org/kernel/pkg/functionscaler/requestqueue"
	"yuanrong.org/kernel/pkg/functionscaler/scheduler"
	"yuanrong.org/kernel/pkg/functionscaler/selfregister"
	"yuanrong.org/kernel/pkg/functionscaler/types"
)

func TestNewReservedConcurrencyScheduler(t *testing.T) {
	InsThdReqQueue := requestqueue.NewInsAcqReqQueue("", 100*time.Millisecond)
	rcs := NewReservedConcurrencyScheduler(&types.FunctionSpecification{
		FuncKey:          "testFunction",
		InstanceMetaData: commontypes.InstanceMetaData{ConcurrentNum: 1},
	}, resspeckey.ResSpecKey{}, 0, InsThdReqQueue)
	assert.NotNil(t, rcs)
}

func TestAcquireInstanceReservedNew(t *testing.T) {
	config.GlobalConfig.LeaseSpan = 5000
	defer func() {
		config.GlobalConfig.LeaseSpan = 0
	}()
	defer gomonkey.ApplyGlobalVar(&requestqueue.DefaultRequestTimeout, 100*time.Millisecond).Reset()
	defer gomonkey.ApplyFunc((*selfregister.SchedulerProxy).IsFuncOwner, func(_ *selfregister.SchedulerProxy,
		funcKey string) bool {
		return true
	}).Reset()
	defer gomonkey.ApplyMethod(reflect.TypeOf(&fakeInstanceScaler{}), "GetExpectInstanceNumber",
		func(f *fakeInstanceScaler) int {
			return 1
		}).Reset()
	defer gomonkey.ApplyFunc((*lease.GenericInstanceLeaseManager).CreateInstanceLease,
		func(_ *lease.GenericInstanceLeaseManager,
			insAlloc *types.InstanceAllocation, interval time.Duration, callback func()) (types.InstanceLease, error) {
			return nil, nil
		}).Reset()
	InsThdReqQueue := requestqueue.NewInsAcqReqQueue("", 100*time.Millisecond)
	rcs := NewReservedConcurrencyScheduler(&types.FunctionSpecification{
		FuncKey:          "testFunction",
		InstanceMetaData: commontypes.InstanceMetaData{ConcurrentNum: 1},
	}, resspeckey.ResSpecKey{}, 50*time.Millisecond, InsThdReqQueue)
	rcs.ConnectWithInstanceScaler(&fakeInstanceScaler{
		scaling: true,
		timer:   time.NewTimer(100 * time.Millisecond),
	})

	rcs.HandleCreateError(errors.New("some error"))
	_, err := rcs.AcquireInstance(&types.InstanceAcquireRequest{})
	assert.Equal(t, "some error", err.Error())
	rcs.HandleCreateError(snerror.New(4011, "user error"))
	_, err = rcs.AcquireInstance(&types.InstanceAcquireRequest{})

	rcs.AddInstance(&types.Instance{
		InstanceID:     "instance1",
		ConcurrentNum:  1,
		ResKey:         resspeckey.ResSpecKey{},
		InstanceStatus: commontypes.InstanceStatus{Code: int32(constant.KernelInstanceStatusRunning)},
	})
	rcs.HandleCreateError(nil)
	insAlloc1, err := rcs.AcquireInstance(&types.InstanceAcquireRequest{DesignateInstanceID: "instance1"})
	assert.Equal(t, nil, err)
	assert.Equal(t, "instance1", insAlloc1.Instance.InstanceID)
	_, err = rcs.AcquireInstance(&types.InstanceAcquireRequest{DesignateInstanceID: "instance1"})
	assert.Equal(t, false, err == nil)
}

func TestAcquireInstanceReserved(t *testing.T) {
	InsThdReqQueue := requestqueue.NewInsAcqReqQueue("", 10)
	rcs := NewReservedConcurrencyScheduler(&types.FunctionSpecification{
		FuncKey:          "testFunction",
		InstanceMetaData: commontypes.InstanceMetaData{ConcurrentNum: 2},
	}, resspeckey.ResSpecKey{}, 50*time.Millisecond, InsThdReqQueue)
	rcs.ConnectWithInstanceScaler(&fakeInstanceScaler{
		scaling: true,
		timer:   time.NewTimer(100 * time.Millisecond),
	})
	_, err := rcs.AcquireInstance(&types.InstanceAcquireRequest{})
	assert.Equal(t, scheduler.ErrNoInsAvailable, err)
	rcs.ConnectWithInstanceScaler(&fakeInstanceScaler{
		scaling: true,
		timer:   time.NewTimer(10 * time.Millisecond),
	})
	_, err = rcs.AcquireInstance(&types.InstanceAcquireRequest{})
	assert.Equal(t, scheduler.ErrNoInsAvailable, err)
	_, err = rcs.AcquireInstance(&types.InstanceAcquireRequest{DesignateInstanceID: "instance1"})
	assert.Equal(t, scheduler.ErrInsNotExist, err)
	rcs.AddInstance(&types.Instance{
		InstanceID:     "instance1",
		ConcurrentNum:  2,
		ResKey:         resspeckey.ResSpecKey{},
		InstanceStatus: commontypes.InstanceStatus{Code: int32(constant.KernelInstanceStatusRunning)},
	})
	acqIns1, err := rcs.AcquireInstance(&types.InstanceAcquireRequest{})
	assert.Nil(t, err)
	assert.Equal(t, "instance1", acqIns1.Instance.InstanceID)
	rcs.AddInstance(&types.Instance{
		InstanceID:     "instance2",
		ConcurrentNum:  2,
		ResKey:         resspeckey.ResSpecKey{},
		InstanceStatus: commontypes.InstanceStatus{Code: int32(constant.KernelInstanceStatusRunning)},
	})
	acqIns2, err := rcs.AcquireInstance(&types.InstanceAcquireRequest{})
	assert.Nil(t, err)
	assert.Equal(t, "instance2", acqIns2.Instance.InstanceID)
	acqIns3, err := rcs.AcquireInstance(&types.InstanceAcquireRequest{DesignateInstanceID: "instance1"})
	assert.Nil(t, err)
	assert.Equal(t, "instance1", acqIns3.Instance.InstanceID)
	_, err = rcs.AcquireInstance(&types.InstanceAcquireRequest{DesignateInstanceID: "instance3"})
	assert.Equal(t, "instance does not exist in queue", err.Error())

	rc := NewReservedConcurrencyScheduler(&types.FunctionSpecification{
		FuncKey:          "testFunction",
		InstanceMetaData: commontypes.InstanceMetaData{ConcurrentNum: 2},
	}, resspeckey.ResSpecKey{}, 150*time.Millisecond, InsThdReqQueue)
	rc.ConnectWithInstanceScaler(&fakeInstanceScaler{
		scaling:         true,
		timer:           time.NewTimer(100 * time.Millisecond),
		targetRsvInsNum: 2,
	})
	rc.HandleCreateError(errors.New("resource not enough"))
	_, err = rc.AcquireInstance(&types.InstanceAcquireRequest{})
	go func() {
		time.Sleep(80 * time.Millisecond)
		rc.HandleCreateError(nil)
	}()
	assert.Equal(t, "resource not enough", err.Error())
}

func TestPopInstanceReserved(t *testing.T) {
	defer gomonkey.ApplyFunc((*selfregister.SchedulerProxy).IsFuncOwner, func(_ *selfregister.SchedulerProxy,
		funcKey string) bool {
		return true
	}).Reset()
	InsThdReqQueue := requestqueue.NewInsAcqReqQueue("", 10)
	rcs := NewReservedConcurrencyScheduler(&types.FunctionSpecification{
		FuncKey:          "testFunction",
		InstanceMetaData: commontypes.InstanceMetaData{ConcurrentNum: 2},
	}, resspeckey.ResSpecKey{}, 50*time.Millisecond, InsThdReqQueue)
	rcs.ConnectWithInstanceScaler(&fakeInstanceScaler{})
	popIns1 := rcs.PopInstance(false)
	assert.Nil(t, popIns1)
	rcs.AddInstance(&types.Instance{
		InstanceID:     "instance1",
		ConcurrentNum:  2,
		ResKey:         resspeckey.ResSpecKey{},
		InstanceStatus: commontypes.InstanceStatus{Code: int32(constant.KernelInstanceStatusRunning)},
	})
	rcs.AddInstance(&types.Instance{
		InstanceID:     "instance2",
		ConcurrentNum:  2,
		ResKey:         resspeckey.ResSpecKey{},
		InstanceStatus: commontypes.InstanceStatus{Code: int32(constant.KernelInstanceStatusRunning)},
	})
	rcs.AcquireInstance(&types.InstanceAcquireRequest{DesignateInstanceID: "instance1"})
	popIns2 := rcs.PopInstance(false)
	assert.Equal(t, "instance2", popIns2.InstanceID)
}

// TestPopInstanceWakesAfterAddInstance is a regression test for the bcs.Cond.Wait() hang:
// popInstanceElement parks on bcs.Wait() when a reserved PopInstance(false) hits an empty self
// queue while still scaling. Before the fix nothing ever signalled this Cond, so the caller (the
// single funcSpecCh goroutine in production) froze forever and surfaced as "pool not exist"/150424.
// AddInstance must now Broadcast so the awaited instance wakes the waiter and is returned.
func TestPopInstanceWakesAfterAddInstance(t *testing.T) {
	defer gomonkey.ApplyFunc((*selfregister.SchedulerProxy).IsFuncOwner, func(_ *selfregister.SchedulerProxy,
		funcKey string) bool {
		return true
	}).Reset()
	InsThdReqQueue := requestqueue.NewInsAcqReqQueue("", 100*time.Millisecond)
	rcs := NewReservedConcurrencyScheduler(&types.FunctionSpecification{
		FuncKey:          "testFunction",
		InstanceMetaData: commontypes.InstanceMetaData{ConcurrentNum: 1},
	}, resspeckey.ResSpecKey{}, 50*time.Millisecond, InsThdReqQueue)
	// Owner instances land in selfInstanceQueue, which is exactly the queue popInstanceElement waits on.
	rcs.(*ReservedConcurrencyScheduler).isFuncOwner = true
	// CheckScaling()==true (scaling, timer far in the future) makes PopInstance(false) set wait=true.
	rcs.ConnectWithInstanceScaler(&fakeInstanceScaler{
		scaling: true,
		timer:   time.NewTimer(time.Hour),
	})

	// Control: force=true => wait=false => returns immediately on an empty queue.
	assert.Nil(t, rcs.PopInstance(true))

	done := make(chan *types.Instance, 1)
	go func() {
		// empty self queue + scaling => popInstanceElement parks on bcs.Wait()
		done <- rcs.PopInstance(false)
	}()

	// Must be parked on Wait(): it cannot return before an instance is enqueued.
	select {
	case <-done:
		t.Fatal("PopInstance(false) returned before AddInstance; expected it to park on bcs.Wait()")
	case <-time.After(300 * time.Millisecond):
	}

	// Enqueue the awaited instance. The fix's Broadcast in AddInstance must wake the waiter.
	assert.Nil(t, rcs.AddInstance(&types.Instance{
		InstanceID:     "instance1",
		ConcurrentNum:  1,
		ResKey:         resspeckey.ResSpecKey{},
		InstanceStatus: commontypes.InstanceStatus{Code: int32(constant.KernelInstanceStatusRunning)},
	}))
	select {
	case ins := <-done:
		assert.NotNil(t, ins)
		assert.Equal(t, "instance1", ins.InstanceID)
	case <-time.After(2 * time.Second):
		t.Fatal("PopInstance(false) still blocked after AddInstance; bcs.Cond.Wait() never woken")
	}
}

func TestHandleFuncSpecUpdateReserved(t *testing.T) {
	InsThdReqQueue := requestqueue.NewInsAcqReqQueue("", 10)
	rcs := NewReservedConcurrencyScheduler(&types.FunctionSpecification{
		FuncKey:          "testFunction",
		InstanceMetaData: commontypes.InstanceMetaData{ConcurrentNum: 2},
	}, resspeckey.ResSpecKey{}, 50*time.Millisecond, InsThdReqQueue)
	rcs.ConnectWithInstanceScaler(&fakeInstanceScaler{})
	rcs.HandleFuncSpecUpdate(&types.FunctionSpecification{
		InstanceMetaData: commontypes.InstanceMetaData{
			ConcurrentNum: 4,
		},
	})
}

func TestHandleFuncSpecUpdateReservedPriorityAZ(t *testing.T) {
	InsThdReqQueue := requestqueue.NewInsAcqReqQueue("", 10)
	rcs := NewReservedConcurrencyScheduler(&types.FunctionSpecification{
		FuncKey:          "testFunction",
		InstanceMetaData: commontypes.InstanceMetaData{ConcurrentNum: 2},
	}, resspeckey.ResSpecKey{}, 50*time.Millisecond, InsThdReqQueue)
	reservedScheduler := rcs.(*ReservedConcurrencyScheduler)
	assert.Nil(t, reservedScheduler.AddInstance(&types.Instance{
		InstanceID:     "instance-az2",
		ConcurrentNum:  2,
		AZ:             "az2",
		ResKey:         resspeckey.ResSpecKey{},
		InstanceStatus: commontypes.InstanceStatus{Code: int32(constant.KernelInstanceStatusRunning)},
	}))
	assert.Nil(t, reservedScheduler.AddInstance(&types.Instance{
		InstanceID:     "instance-az1",
		ConcurrentNum:  2,
		AZ:             "az1",
		ResKey:         resspeckey.ResSpecKey{},
		InstanceStatus: commontypes.InstanceStatus{Code: int32(constant.KernelInstanceStatusRunning)},
	}))
	rcs.ConnectWithInstanceScaler(&fakeInstanceScaler{})
	rcs.HandleFuncSpecUpdate(&types.FunctionSpecification{
		InstanceMetaData: commontypes.InstanceMetaData{
			ConcurrentNum: 2,
		},
		ExtendedMetaData: commontypes.ExtendedMetaData{
			PriorityAZ: "az1",
		},
	})
	assert.Equal(t, "instance-az1", reservedScheduler.otherInstanceQueue.Front().(*instanceElement).instance.InstanceID)
}

func TestPriorityFuncForReservedInstanceBonus(t *testing.T) {
	priorityFunc := priorityFuncForReservedInstance
	preferredNewWeight, err := priorityFunc(&instanceElement{
		instance:      &types.Instance{ConcurrentNum: 2, AZ: "az1"},
		threadMap:     map[string]struct{}{"thread1": {}},
		isNewInstance: true,
		isPriorityAZ:  true,
	})
	assert.Nil(t, err)
	newWeight, err := priorityFunc(&instanceElement{
		instance:      &types.Instance{ConcurrentNum: 2, AZ: "az2"},
		threadMap:     map[string]struct{}{"thread1": {}},
		isNewInstance: true,
	})
	assert.Nil(t, err)
	oldWeight, err := priorityFunc(&instanceElement{
		instance:      &types.Instance{ConcurrentNum: 2, AZ: "az1"},
		threadMap:     map[string]struct{}{"thread1": {}},
		isNewInstance: false,
	})
	assert.Nil(t, err)
	assert.Greater(t, preferredNewWeight, newWeight)
	assert.Greater(t, newWeight, oldWeight)
}

func TestPriorityFuncForReservedInstanceFallback(t *testing.T) {
	priorityFunc := priorityFuncForReservedInstance
	exhaustedPriorityWeight, err := priorityFunc(&instanceElement{
		instance:      &types.Instance{ConcurrentNum: 2, AZ: "az1"},
		threadMap:     map[string]struct{}{},
		isNewInstance: true,
		isPriorityAZ:  true,
	})
	assert.Nil(t, err)
	availableOldWeight, err := priorityFunc(&instanceElement{
		instance:      &types.Instance{ConcurrentNum: 2, AZ: "az1"},
		threadMap:     map[string]struct{}{"thread1": {}},
		isNewInstance: false,
	})
	assert.Nil(t, err)
	assert.Less(t, exhaustedPriorityWeight, availableOldWeight)
}

func TestAddInstancePublishReserved(t *testing.T) {
	defer gomonkey.ApplyFunc((*selfregister.SchedulerProxy).IsFuncOwner, func(_ *selfregister.SchedulerProxy,
		funcKey string) bool {
		return true
	}).Reset()
	config.GlobalConfig.AutoScaleConfig.BurstScaleNum = 1000
	InsThdReqQueue := requestqueue.NewInsAcqReqQueue("testFunction", 50*time.Millisecond)
	insThdReq1 := &requestqueue.PendingInsAcqReq{
		ResultChan: make(chan *requestqueue.PendingInsAcqRsp, 1),
		InsAcqReq:  &types.InstanceAcquireRequest{},
	}
	insThdReq2 := &requestqueue.PendingInsAcqReq{
		ResultChan: make(chan *requestqueue.PendingInsAcqRsp, 1),
		InsAcqReq:  &types.InstanceAcquireRequest{},
	}
	InsThdReqQueue.AddRequest(insThdReq1)
	InsThdReqQueue.AddRequest(insThdReq2)
	rcs := NewReservedConcurrencyScheduler(&types.FunctionSpecification{
		FuncKey:          "testFunction",
		InstanceMetaData: commontypes.InstanceMetaData{ConcurrentNum: 2},
	}, resspeckey.ResSpecKey{}, 50*time.Millisecond, InsThdReqQueue)
	rcs.AddInstance(&types.Instance{
		InstanceID:    "instance1",
		ConcurrentNum: 2,
		ResKey:        resspeckey.ResSpecKey{},
		InstanceStatus: commontypes.InstanceStatus{
			Code: int32(constant.KernelInstanceStatusRunning),
		},
	})
	time.Sleep(10 * time.Millisecond)
	select {
	case insThd := <-insThdReq1.ResultChan:
		assert.Equal(t, "instance1", insThd.InsAlloc.Instance.InstanceID)
	default:
		t.Errorf("should get instance from result channel")
	}
	select {
	case insThd := <-insThdReq2.ResultChan:
		assert.Equal(t, "instance1", insThd.InsAlloc.Instance.InstanceID)
	default:
		t.Errorf("should get instance from result channel")
	}
}
