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
	"go.uber.org/zap"
	"yuanrong.org/kernel/pkg/common/faas_common/logger/log"
	"yuanrong.org/kernel/pkg/functionscaler/scaler"
)

// noopSender is a placeholder ScaleHintSender that logs hints but does not dispatch
// them. It exists so that LiteScheduler's cold-start path (construct hint -> send ->
// waitForInstance) is fully exercised in unit tests and local dev without requiring
// a real scaler backend.
//
// Future implementations:
//   - httpSender: POST ScaleHint as JSON to a remote scaler service.
//   - grpcSender: stream ScaleHints over gRPC to a remote scaler service.
//
// The ScaleHintSender interface is the single seam; swapping noopSender for a real
// sender requires no changes to operation.go or litescheduler.go.
type noopSender struct{}

// NewNoopSender constructs a no-op ScaleHintSender suitable for testing and local
// development. Production code should inject a real sender (httpSender/grpcSender)
// when available.
func NewNoopSender() ScaleHintSender {
	return &noopSender{}
}

func (n *noopSender) Send(hint *scaler.ScaleHint) {
	if hint == nil {
		return
	}
	log.GetLogger().With(zap.String("funcKey", hint.FuncKey),
		zap.String("sessionID", hint.SessionID), zap.String("traceID", hint.TraceID)).
		Debug("lite scaleHint noop (no scaler backend configured)")
}
