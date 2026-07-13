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

// Package concurrencyscheduler -
package concurrencyscheduler

import (
	"math"
	"testing"

	"github.com/stretchr/testify/assert"

	"yuanrong.org/kernel/pkg/functionscaler/rollout"
)

func TestNewHashBasedInstanceAllocator(t *testing.T) {
	allocator := NewHashBasedInstanceAllocator(0.5)
	assert.NotNil(t, allocator)
	assert.Equal(t, 0.5, allocator.GetRolloutRatio())
}

func TestCountFloorGrayCount(t *testing.T) {
	allocator := &HashBasedInstanceAllocator{
		hasher:       &CRC32Hasher{},
		rolloutRatio: 0.3,
		maxHashValue: math.MaxUint32,
		boundaryHash: math.MaxUint32,
	}
	assert.Equal(t, 0, allocator.CountFloorGrayCount(3))
	assert.Equal(t, 3, allocator.CountFloorGrayCount(10))
	assert.Equal(t, 30, allocator.CountFloorGrayCount(100))
}

func TestModifyCount(t *testing.T) {
	allocator := &HashBasedInstanceAllocator{
		hasher:       &CRC32Hasher{},
		rolloutRatio: 0.5,
		maxHashValue: math.MaxUint32,
		boundaryHash: math.MaxUint32,
	}
	allocator.modifyCount(Add, "instance1")
	allocator.modifyCount(Add, "instance2")
	allocator.modifyCount(Del, "instance1")
	assert.Equal(t, 0, allocator.grayCount)
	assert.Equal(t, 1, allocator.notGrayCount)
}

func TestCheckSelf(t *testing.T) {
	allocator := &HashBasedInstanceAllocator{
		hasher:       &CRC32Hasher{},
		rolloutRatio: 0.5,
		maxHashValue: math.MaxUint32,
		boundaryHash: math.MaxUint32,
	}
	allocator.boundaryHash = 1000
	assert.False(t, allocator.CheckSelf(false, "instance1"))
	assert.True(t, allocator.CheckSelf(true, "instance1"))
}

func TestPartition(t *testing.T) {
	allocator := &HashBasedInstanceAllocator{
		hasher:       &CRC32Hasher{},
		rolloutRatio: 0.5,
		maxHashValue: math.MaxUint32,
		boundaryHash: math.MaxUint32,
	}
	instances := []*HashedInstance{
		{InsElem: &instanceElement{}, hash: 500},
		{InsElem: &instanceElement{}, hash: 1500},
		{InsElem: &instanceElement{}, hash: 2500},
	}
	self, other := allocator.Partition(instances, false)
	assert.Equal(t, 2, len(self))
	assert.Equal(t, 1, len(other))
	assert.Equal(t, uint32(1500), allocator.boundaryHash)
}

func TestShouldReassign(t *testing.T) {
	allocator := &HashBasedInstanceAllocator{
		hasher:       &CRC32Hasher{},
		rolloutRatio: 0.5,
		maxHashValue: math.MaxUint32,
		boundaryHash: math.MaxUint32,
	}
	allocator.grayCount = 1
	allocator.notGrayCount = 1
	rollout.GetGlobalRolloutConfig().SetUpdating(true)

	assert.False(t, allocator.ShouldReassign(Add, "instance1"))
	assert.False(t, allocator.ShouldReassign(Del, "instance1"))
	rollout.GetGlobalRolloutConfig().SetUpdating(false)
}

func TestComputeHash(t *testing.T) {
	allocator := NewHashBasedInstanceAllocator(0.5)
	hashValue := allocator.ComputeHash("instance1")
	assert.NotEqual(t, 0, hashValue)
}

func TestUpdateRolloutRatio(t *testing.T) {
	allocator := NewHashBasedInstanceAllocator(0.5)
	allocator.UpdateRolloutRatio(75)
	assert.Equal(t, 0.75, allocator.GetRolloutRatio())
}
