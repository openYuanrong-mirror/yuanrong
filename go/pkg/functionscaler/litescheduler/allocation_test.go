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
)

func TestGenAllocationIDFormat(t *testing.T) {
	convey.Convey("genAllocationID produces lite prefix format", t, func() {
		allocID := genAllocationID("tenant1/sessionXYZ", "ins123", 7)
		convey.So(allocID, convey.ShouldStartWith, "lite:")
		// format: lite:{16hex}:{instanceID}:thread:{seq}
		convey.So(allocID, convey.ShouldEndWith, ":ins123:thread:7")
	})
}

func TestSessionHashIsSha256PrefixAndNotFullSession(t *testing.T) {
	convey.Convey("sessionHash is 16-hex sha256 prefix, not full sessionID", t, func() {
		h := sessionHash("tenant1/sessionXYZ")
		convey.So(len(h), convey.ShouldEqual, 16)
		convey.So(h, convey.ShouldNotContainSubstring, "sessionXYZ")
	})
}

func TestParseLiteAllocationID(t *testing.T) {
	convey.Convey("parse lite allocationID", t, func() {
		allocID := genAllocationID("tenant1/sess1", "ins1", 3)
		isLite, hash, instanceID, seq := parseLiteAllocationID(allocID)
		convey.So(isLite, convey.ShouldBeTrue)
		convey.So(hash, convey.ShouldEqual, sessionHash("tenant1/sess1"))
		convey.So(instanceID, convey.ShouldEqual, "ins1")
		convey.So(seq, convey.ShouldEqual, 3)
	})
	convey.Convey("parse non-lite allocationID", t, func() {
		isLite, _, _, _ := parseLiteAllocationID("ins123-thread1")
		convey.So(isLite, convey.ShouldBeFalse)
	})
}

// TestParseLiteAllocationIDEdgeCases pins the contract for boundary inputs.
// These cases document the current (intended) parse behavior to prevent
// future maintainers from silently changing semantics.
//
// Notable decisions:
//   - seq=0 is a valid allocation (Atoi("0")=0, no error).
//   - A bare "lite:" prefix is rejected (SplitN yields 1 part, not 3).
//   - The thread segment must literally start with "thread:"; any other
//     content (including a colon-bearing instanceID that shifts segments)
//     causes the third SplitN part to not start with "thread:" and is rejected.
//   - seq must be a base-10 integer; non-numeric seq is rejected.
//   - An instanceID containing ':' breaks the gen->parse round-trip because
//     SplitN(rest, ":", 3) consumes the first two ':' as separators and the
//     remainder (including the real "thread:N") becomes the thread segment,
//     which then does not start with "thread:". This is a documented
//     limitation: instanceID must not contain ':'.
func TestParseLiteAllocationIDEdgeCases(t *testing.T) {
	convey.Convey("parse edge cases", t, func() {
		cases := []struct {
			name       string
			allocID    string
			wantIsLite bool
			wantInstID string
			wantSeq    int
		}{
			{"seq zero is valid", genAllocationID("t/s", "ins", 0), true, "ins", 0},
			{"only prefix", "lite:", false, "", 0},
			{"thread segment mismatch", "lite:abc:ins:notthread:5", false, "", 0},
			{"seq not a number", "lite:abc:ins:thread:xyz", false, "", 0},
			{"instanceID with colon breaks round-trip", "lite:abc:ins:1:thread:5", false, "", 0},
		}
		for _, c := range cases {
			convey.Convey(c.name, func() {
				isLite, _, instID, seq := parseLiteAllocationID(c.allocID)
				convey.So(isLite, convey.ShouldEqual, c.wantIsLite)
				if c.wantIsLite {
					convey.So(instID, convey.ShouldEqual, c.wantInstID)
					convey.So(seq, convey.ShouldEqual, c.wantSeq)
				}
			})
		}
	})
}
