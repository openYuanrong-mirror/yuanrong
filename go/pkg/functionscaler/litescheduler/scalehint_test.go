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

	"github.com/stretchr/testify/assert"

	"yuanrong.org/kernel/pkg/functionscaler/scaler"
)

func TestNoopSenderNilHintDoesNotPanic(t *testing.T) {
	s := NewNoopSender()
	assert.NotPanics(t, func() {
		s.Send(nil)
	})
}

func TestNoopSenderSendsWithoutPanic(t *testing.T) {
	s := NewNoopSender()
	assert.NotPanics(t, func() {
		s.Send(&scaler.ScaleHint{FuncKey: "unknown/f/v1", Reason: "cold_start"})
	})
}
