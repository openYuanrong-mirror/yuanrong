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

package selfregister

import (
	"fmt"
	"testing"
	"time"

	"github.com/agiledragon/gomonkey/v2"
	"github.com/smartystreets/goconvey/convey"

	"yuanrong.org/kernel/pkg/common/faas_common/loadbalance"
	"yuanrong.org/kernel/pkg/common/faas_common/types"
)

func Test_schedulerProxy_DealFilter(t *testing.T) {
	convey.Convey("test_deal_filter", t, func() {
		convey.Convey("base", func() {

			proxy := NewSchedulerProxy(loadbalance.NewCHGeneric())

			proxy.Add(&types.InstanceInfo{
				InstanceName: "aa2794fb-dc9e-420d-ae54-bedfa3577930",
			}, "", "", true)

			proxy.Add(&types.InstanceInfo{
				InstanceName: "7d3f736e-b2b0-4b7e-bc8d-3a390ec0ed31",
			}, "", "", true)

			proxy.Add(&types.InstanceInfo{
				InstanceName: "d06832bc-8c02-4589-9c37-edae4109302d",
			}, "", "", true)

			SelfInstanceID = "aa2794fb-dc9e-420d-ae54-bedfa3577930"

			flag := proxy.IsFuncOwner("244177614494719500/0@default@testcustom001/latest")

			convey.So(flag, convey.ShouldBeFalse)

			proxy.Remove("d06832bc-8c02-4589-9c37-edae4109302d", "", true)

			flag = proxy.IsFuncOwner("244177614494719500/0@default@testcustom001/latest")

			convey.So(flag, convey.ShouldBeFalse)

			proxy.Remove("7d3f736e-b2b0-4b7e-bc8d-3a390ec0ed31", "", true)

			flag = proxy.IsFuncOwner("244177614494719500/0@default@testcustom001/latest")

			convey.So(flag, convey.ShouldBeTrue)

			proxy.Add(&types.InstanceInfo{
				InstanceName: "d06832bc-8c02-4589-9c37-edae4109302d",
			}, "", "", true)

			flag = proxy.IsFuncOwner("244177614494719500/0@default@testcustom001/latest")

			convey.So(flag, convey.ShouldBeTrue)

			proxy.Add(&types.InstanceInfo{
				InstanceName: "7d3f736e-b2b0-4b7e-bc8d-3a390ec0ed31",
			}, "", "", true)

			proxy.Reset()

			flag = proxy.IsFuncOwner("244177614494719500/0@default@testcustom001/latest")

			convey.So(flag, convey.ShouldBeFalse)
		})
	})
}

func TestDealFilter(t *testing.T) {
	proxy := NewSchedulerProxy(loadbalance.NewSimpleCHGeneric())
	convey.Convey("start failed", t, func() {
		res := proxy.IsFuncOwner("mock-funcKey")
		convey.So(res, convey.ShouldBeFalse)
	})
	proxy.Add(&types.InstanceInfo{
		InstanceName: "scheduler-001",
	}, "", "", true)
	convey.Convey("start failed", t, func() {
		res := proxy.IsFuncOwner("mock-funcKey")
		convey.So(res, convey.ShouldBeFalse)
	})
	SelfInstanceID = "scheduler-001"
	convey.Convey("start success", t, func() {
		res := proxy.IsFuncOwner("mock-funcKey")
		convey.So(res, convey.ShouldBeTrue)
	})
	proxy.FaaSSchedulers.Delete("scheduler-001")
	convey.Convey("start failed", t, func() {
		res := proxy.IsFuncOwner("mock-funcKey")
		convey.So(res, convey.ShouldBeFalse)
	})
}

func TestContains(t *testing.T) {
	proxy := NewSchedulerProxy(loadbalance.NewSimpleCHGeneric())
	convey.Convey("not contains", t, func() {
		res := proxy.Contains("instance1")
		convey.So(res, convey.ShouldBeFalse)
	})
}

func Test(t *testing.T) {
	proxy := NewSchedulerProxy(loadbalance.NewSimpleCHGeneric())
	callTime := 0
	defer gomonkey.ApplyFunc(time.Sleep, func(d time.Duration) {
		callTime++
	}).Reset()
	convey.Convey("wait for hash", t, func() {
		proxy.WaitForHash(0)
		convey.So(callTime, convey.ShouldEqual, 0)
		proxy.FaaSSchedulers.Store("instance1", nil)
		proxy.WaitForHash(1)
		convey.So(callTime, convey.ShouldEqual, 0)
	})
}

func TestCheckHashOwnerEquivalentToCheckFuncOwner(t *testing.T) {
	convey.Convey("CheckHashOwner returns same result as CheckFuncOwner for same key", t, func() {
		// 构造一个含 2 个 scheduler 的 proxy
		sp := NewSchedulerProxy(loadbalance.NewSimpleCHGeneric())
		sp.Add(&types.InstanceInfo{InstanceID: "s1", InstanceName: "n1"}, "", "", true)
		sp.Add(&types.InstanceInfo{InstanceID: "s2", InstanceName: "n2"}, "", "", true)
		funcKey := "tenant1/funcA/v1"
		ownerID1, ok1 := sp.CheckFuncOwner(funcKey)
		ownerID2, ok2 := sp.CheckHashOwner(funcKey)
		convey.So(ownerID1, convey.ShouldEqual, ownerID2)
		convey.So(ok1, convey.ShouldEqual, ok2)
	})
	convey.Convey("CheckHashOwner different key may hit different owner", t, func() {
		sp := NewSchedulerProxy(loadbalance.NewSimpleCHGeneric())
		sp.Add(&types.InstanceInfo{InstanceID: "s1", InstanceName: "n1"}, "", "", true)
		sp.Add(&types.InstanceInfo{InstanceID: "s2", InstanceName: "n2"}, "", "", true)
		// session 维度 key：仅验证不 panic，owned 状态由 ring 决定
		_, okFunc := sp.CheckHashOwner("tenant1/funcA/v1")
		_, okSession := sp.CheckHashOwner("tenant1/sessionXYZ")
		_ = okFunc
		_ = okSession
	})
}

func TestSchedulerProxyFindHashOwner(t *testing.T) {
	convey.Convey("single node ring returns self as owner", t, func() {
		proxy := NewSchedulerProxy(loadbalance.NewCHGeneric())
		proxy.Add(&types.InstanceInfo{
			InstanceName: "sched-1",
			InstanceID:   "id-1",
			Address:      "10.0.0.1:8080",
		}, "", "", true)
		oldSelf := SelfInstanceID
		SelfInstanceID = "sched-1"
		defer func() { SelfInstanceID = oldSelf }()

		info, owned := proxy.FindHashOwner("tenantA/fA/v1")
		convey.So(info, convey.ShouldNotBeNil)
		convey.So(info.Address, convey.ShouldEqual, "10.0.0.1:8080")
		convey.So(owned, convey.ShouldBeTrue)
	})
	convey.Convey("empty ring returns nil", t, func() {
		proxy := NewSchedulerProxy(loadbalance.NewCHGeneric())
		info, owned := proxy.FindHashOwner("tenantA/fA/v1")
		convey.So(info, convey.ShouldBeNil)
		convey.So(owned, convey.ShouldBeFalse)
	})
	convey.Convey("remote owner returns its address with owned=false", t, func() {
		proxy := NewSchedulerProxy(loadbalance.NewCHGeneric())
		proxy.Add(&types.InstanceInfo{
			InstanceName: "sched-1",
			InstanceID:   "id-1",
			Address:      "10.0.0.1:8080",
		}, "", "", true)
		proxy.Add(&types.InstanceInfo{
			InstanceName: "sched-2",
			InstanceID:   "id-2",
			Address:      "10.0.0.2:8080",
		}, "", "", true)
		oldSelf := SelfInstanceID
		SelfInstanceID = "sched-1"
		defer func() { SelfInstanceID = oldSelf }()

		var info *types.InstanceInfo
		var owned bool
		var hitKey string
		for i := 0; i < 100; i++ {
			key := fmt.Sprintf("key-%d", i)
			info, owned = proxy.FindHashOwner(key)
			convey.So(info, convey.ShouldNotBeNil)
			if info.InstanceName == "sched-2" {
				hitKey = key
				break
			}
		}
		convey.So(hitKey, convey.ShouldNotEqual, "")
		convey.So(owned, convey.ShouldBeFalse)
		convey.So(info.Address, convey.ShouldEqual, "10.0.0.2:8080")

		// cross-check consistency with CheckHashOwner for the same hash key
		ownerID, checkOwned := proxy.CheckHashOwner(hitKey)
		convey.So(ownerID, convey.ShouldEqual, info.InstanceID)
		convey.So(checkOwned, convey.ShouldEqual, owned)
	})
}

func TestSchedulerProxyFindByInstanceID(t *testing.T) {
	convey.Convey("find by instance id", t, func() {
		proxy := NewSchedulerProxy(loadbalance.NewCHGeneric())
		proxy.Add(&types.InstanceInfo{InstanceName: "sched-1", InstanceID: "id-1",
			Address: "10.0.0.1:8080"}, "", "", true)
		proxy.Add(&types.InstanceInfo{InstanceName: "sched-2", InstanceID: "id-2",
			Address: "10.0.0.2:8080"}, "", "", true)
		info := proxy.FindByInstanceID("id-2")
		convey.So(info, convey.ShouldNotBeNil)
		convey.So(info.Address, convey.ShouldEqual, "10.0.0.2:8080")
		convey.So(proxy.FindByInstanceID("id-x"), convey.ShouldBeNil)
	})
}
