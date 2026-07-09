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

package rollout

import (
	"testing"

	"github.com/smartystreets/goconvey/convey"
)

func TestProcessRatioUpdate(t *testing.T) {
	convey.Convey("test process ratio update", t, func() {
		err := globalRolloutConfig.ProcessRatioUpdate(nil)
		convey.So(err, convey.ShouldNotBeNil)

		err = globalRolloutConfig.ProcessRatioUpdate([]byte(`{"blue-ratio":"invalid 500%"}`))
		convey.So(err, convey.ShouldNotBeNil)
		convey.So(err.Error(), convey.ShouldContainSubstring, "invalid")

		err = globalRolloutConfig.ProcessRatioUpdate([]byte(`{"blue-ratio":"500%"}`))
		convey.So(err, convey.ShouldNotBeNil)
		convey.So(err.Error(), convey.ShouldContainSubstring, "blue ratio larger than")

		err = globalRolloutConfig.ProcessRatioUpdate([]byte(`{"blue-ratio":"50%"}`))
		convey.So(err, convey.ShouldBeNil)
		convey.So(globalRolloutConfig.GetCurrentRatio(), convey.ShouldEqual, 50)
		convey.So(globalRolloutConfig.IsUpdating(), convey.ShouldEqual, true)

		err = globalRolloutConfig.ProcessRatioUpdate([]byte(`{"blue-ratio":"0"}`))
		convey.So(err, convey.ShouldBeNil)
		convey.So(globalRolloutConfig.GetCurrentRatio(), convey.ShouldEqual, 0)
		convey.So(globalRolloutConfig.IsUpdating(), convey.ShouldEqual, false)

		err = globalRolloutConfig.ProcessRatioUpdate([]byte(`{"blue-ratio":"0%"}`))
		convey.So(err, convey.ShouldBeNil)
		convey.So(globalRolloutConfig.GetCurrentRatio(), convey.ShouldEqual, 0)
		convey.So(globalRolloutConfig.IsUpdating(), convey.ShouldEqual, false)

		err = globalRolloutConfig.ProcessRatioUpdate([]byte(`{"blue-ratio":"100"}`))
		convey.So(err, convey.ShouldBeNil)
		convey.So(globalRolloutConfig.GetCurrentRatio(), convey.ShouldEqual, 100)
		convey.So(globalRolloutConfig.IsUpdating(), convey.ShouldEqual, false)
		err = globalRolloutConfig.ProcessRatioUpdate([]byte(`{"blue-ratio":"50%"}`))
		convey.So(err, convey.ShouldBeNil)
		globalRolloutConfig.ProcessRatioDelete()
		convey.So(globalRolloutConfig.GetCurrentRatio(), convey.ShouldEqual, 0)
		convey.So(globalRolloutConfig.IsUpdating(), convey.ShouldEqual, false)
	})
}
