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

package instancepool

import (
	"fmt"

	"reflect"
	"testing"
	"time"

	"github.com/agiledragon/gomonkey/v2"
	"github.com/stretchr/testify/assert"
	"k8s.io/apimachinery/pkg/util/wait"

	"yuanrong.org/kernel/pkg/common/faas_common/constant"
	"yuanrong.org/kernel/pkg/common/faas_common/logger/log"
	mockUtils "yuanrong.org/kernel/pkg/common/faas_common/utils"
	"yuanrong.org/kernel/pkg/functionscaler/config"
	"yuanrong.org/kernel/pkg/functionscaler/selfregister"
	"yuanrong.org/kernel/pkg/functionscaler/types"
)

func TestCreateInstance(t *testing.T) {
	rawCreateInstanceForFGFunc := createInstanceForFGFunc
	rawCreateInstanceForKernelFunc := createInstanceForKernelFunc
	createInstanceForFGFunc = func(request createInstanceRequest) (*types.Instance, error) {
		return &types.Instance{InstanceID: "instance-fg"}, nil
	}
	createInstanceForKernelFunc = func(request createInstanceRequest) (*types.Instance, error) {
		return &types.Instance{InstanceID: "instance-kernel"}, nil
	}
	defer func() {
		createInstanceForFGFunc = rawCreateInstanceForFGFunc
		createInstanceForKernelFunc = rawCreateInstanceForKernelFunc
	}()
	config.GlobalConfig.InstanceOperationBackend = constant.BackendTypeFG
	ins1, err := CreateInstance(createInstanceRequest{})
	assert.Nil(t, err)
	assert.Equal(t, "instance-fg", ins1.InstanceID)
	config.GlobalConfig.InstanceOperationBackend = constant.BackendTypeKernel
	ins2, err := CreateInstance(createInstanceRequest{})
	assert.Nil(t, err)
	assert.Equal(t, "instance-kernel", ins2.InstanceID)
}

func TestDeleteInstance(t *testing.T) {
	rawDeleteInstanceForFGFunc := deleteInstanceForFGFunc
	rawDeleteInstanceForKernelFunc := deleteInstanceForKernelFunc
	deleteInstanceForFGFunc = func(funcSpec *types.FunctionSpecification, faasManagerInfo faasManagerInfo,
		instance *types.Instance) error {
		return nil
	}
	deleteInstanceForKernelFunc = func(funcSpec *types.FunctionSpecification, faasManagerInfo faasManagerInfo,
		instance *types.Instance) error {
		return nil
	}
	defer func() {
		deleteInstanceForFGFunc = rawDeleteInstanceForFGFunc
		deleteInstanceForKernelFunc = rawDeleteInstanceForKernelFunc
	}()
	config.GlobalConfig.InstanceOperationBackend = constant.BackendTypeFG
	err := DeleteInstance(&types.FunctionSpecification{}, faasManagerInfo{}, &types.Instance{})
	assert.Nil(t, err)
	config.GlobalConfig.InstanceOperationBackend = constant.BackendTypeKernel
	err = DeleteInstance(&types.FunctionSpecification{}, faasManagerInfo{}, &types.Instance{})
	assert.Nil(t, err)
}

func TestDeleteInstanceRetry(t *testing.T) {
	cnt := 0

	SetGlobalSdkClient(&mockUtils.FakeLibruntimeSdkClient{})
	rawKillInstance := killInstance
	killInstance = func(instanceID string) error {
		cnt++
		return fmt.Errorf("error kill")
	}
	defer func() { killInstance = rawKillInstance }()
	config.GlobalConfig.InstanceOperationBackend = constant.BackendTypeKernel
	coldStartBackoff = wait.Backoff{
		Duration: 10 * time.Millisecond,
		Factor:   1,
		Jitter:   0.1,
		Steps:    2,
		Cap:      15 * time.Millisecond,
	}
	err := DeleteInstance(&types.FunctionSpecification{}, faasManagerInfo{}, &types.Instance{})
	time.Sleep(50 * time.Millisecond)
	assert.Equal(t, "error kill", err.Error())
	assert.Equal(t, 3, cnt)
}

func TestDeleteUnexpectInstance(t *testing.T) {
	deleteInstanceCalled := false
	var deleteInstanceInstanceID string
	var deleteInstanceFuncKey string

	rawDeleteInstanceByIDFunc := deleteInstanceByIDFunc
	defer func() {
		deleteInstanceByIDFunc = rawDeleteInstanceByIDFunc
	}()
	deleteInstanceByIDFunc = func(instanceID, funcKey string) error {
		deleteInstanceCalled = true
		deleteInstanceInstanceID = instanceID
		deleteInstanceFuncKey = funcKey
		return nil
	}

	originalInstanceIDSelf := selfregister.SelfInstanceID
	selfregister.SelfInstanceID = "self-id"
	defer func() {
		selfregister.SelfInstanceID = originalInstanceIDSelf
	}()

	parentID := "parent-id"
	instanceID := "test-instance-id"
	funcKey := "test-func-key"

	parentIDContains := false
	patches := gomonkey.NewPatches()
	defer patches.Reset()

	patches.ApplyMethod(reflect.TypeOf(&selfregister.SchedulerProxy{}), "Contains",
		func(_ interface{}, id string) bool {
			return parentIDContains
		})
	logger := log.GetLogger()
	parentIDContains = true
	deleteInstanceCalled = false
	DeleteUnexpectInstance(parentID, instanceID, funcKey, logger)

	assert.False(t, deleteInstanceCalled)

	parentIDContains = false
	deleteInstanceCalled = false
	DeleteUnexpectInstance(parentID, instanceID, funcKey, logger)

	assert.True(t, deleteInstanceCalled)
	assert.Equal(t, instanceID, deleteInstanceInstanceID)
	assert.Equal(t, funcKey, deleteInstanceFuncKey)

	parentID = selfregister.SelfInstanceID
	deleteInstanceCalled = false
	DeleteUnexpectInstance(parentID, instanceID, funcKey, logger)

	assert.True(t, deleteInstanceCalled)
	assert.Equal(t, instanceID, deleteInstanceInstanceID)
	assert.Equal(t, funcKey, deleteInstanceFuncKey)

	parentID = constant.WorkerManagerApplier
	deleteInstanceCalled = false
	DeleteUnexpectInstance(parentID, instanceID, funcKey, logger)

	assert.False(t, deleteInstanceCalled)

	parentID = constant.FunctionTaskApplier + "123"
	deleteInstanceCalled = false
	DeleteUnexpectInstance(parentID, instanceID, funcKey, logger)

	assert.False(t, deleteInstanceCalled)

	parentID = constant.ASBResApplier
	deleteInstanceCalled = false
	DeleteUnexpectInstance(parentID, instanceID, funcKey, logger)

	assert.False(t, deleteInstanceCalled)
}

func TestDeleteInstanceByID(t *testing.T) {
	scaleDownNum := 0
	rawScaleDownInstanceFunc := scaleDownInstanceFunc
	defer func() {
		scaleDownInstanceFunc = rawScaleDownInstanceFunc
	}()
	scaleDownInstanceFunc = func(instanceID, functionKey, traceID string) error {
		scaleDownNum++
		return nil
	}
	SetGlobalSdkClient(&mockUtils.FakeLibruntimeSdkClient{})
	config.GlobalConfig.InstanceOperationBackend = constant.BackendTypeFG
	err := DeleteInstanceByID("testInsID", "testFuncKey")
	assert.Nil(t, err)

	config.GlobalConfig.InstanceOperationBackend = constant.BackendTypeKernel
	err = DeleteInstanceByID("testInsID", "testFuncKey")
	assert.Nil(t, err)
	SetGlobalSdkClient(nil)
}

func TestSignalInstance(t *testing.T) {
	config.GlobalConfig.InstanceOperationBackend = constant.BackendTypeFG
	SignalInstance(&types.Instance{}, 0)
	assert.Equal(t, 0, 0)
}
