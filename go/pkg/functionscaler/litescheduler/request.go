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
	"encoding/json"
	"strings"
	"time"

	"go.uber.org/zap"
	"yuanrong.org/kernel/pkg/common/faas_common/constant"
	"yuanrong.org/kernel/pkg/common/faas_common/logger/log"
	commonTypes "yuanrong.org/kernel/pkg/common/faas_common/types"
	"yuanrong.org/kernel/pkg/functionscaler/config"
	"yuanrong.org/kernel/runtime/libruntime/api"
)

// InstanceOperation mirrors faasscheduler.InstanceOperation to avoid import cycle.
type InstanceOperation string

// LiteRequest 是进入 LiteScheduler 分支的已解析请求。
type LiteRequest struct {
	Op                InstanceOperation
	FuncKey           string
	TenantID          string
	SessionID         string
	SessionCtxID      string
	SessionTTL        int // 秒；0 表示用默认值
	Concurrency       int
	AllocationIDs     []string
	ExtraData         []byte
	MetricsData       []byte
	TraceID           string
	NeedReverseLookup bool
	// logger/startTime 为请求级上下文：Process 中填充，ensureReqContext 为绕过
	// Process 的路径（测试、batchRetain 子请求）兜底。调度器是进程级单例，请求级
	// 状态必须放 req 上做请求间隔离，放调度器字段会被并发请求互相覆盖。
	logger    api.FormatLogger
	startTime time.Time
	// bindingKey 为会话绑定键（依赖 pool.funcSpec.EnableSessionCtx，ParseRequest
	// 时 pool 未解析、无法提前计算）。handleAcquire 在 pool.RLock 下计算一次并
	// 缓存于此，acquire 后续阶段复用；并发 spec 换指针时同一请求的 key 也不会
	// 漂移。仅 acquire 路径设置。
	bindingKey string
}

// newReqLogger 构建请求基座 logger：只烧入入口已知且此后不变的字段。
// funcKey 仅 acquire 在入口可知；release/retain/batchRetain 的 funcKey 要等
// reverseLookup/分配解析后才已知，须在各自解析点 With 附加（zap 字段
// append-only，入口烧入空值或代表值都无法事后纠正）。
func newReqLogger(traceID, funcKey string) api.FormatLogger {
	fields := []zap.Field{zap.String("traceID", traceID)}
	if funcKey != "" {
		fields = append(fields, zap.String("funcKey", funcKey))
	}
	return log.GetLogger().With(fields...)
}

// ensureReqContext 懒初始化请求级 logger 和计时起点，兜底绕过 Process 的测试
// 和 batchRetain 子请求。req 不跨 goroutine 共享，无需加锁。
func (req *LiteRequest) ensureReqContext() {
	if req.logger == nil {
		req.logger = newReqLogger(req.TraceID, req.FuncKey)
	}
	if req.startTime.IsZero() {
		req.startTime = time.Now()
	}
}

// ParseRequest is stateless: decides whether to enter the lite branch (ok=false -> legacy).
func (ls *LiteScheduler) ParseRequest(op InstanceOperation, targetName string,
	extraData []byte, traceID string) (req *LiteRequest, ok bool) {
	logger := log.GetLogger()
	traceField := zap.String("traceID", traceID)
	defer func() {
		if r := recover(); r != nil {
			logger.Error("lite parseRequest panic, fallback to legacy path", traceField, zap.Any("panic", r))
			req = nil
			ok = false
		}
	}()

	switch op {
	case "acquire", "release", "retain", "batchRetain":
	default:
		return nil, false // unsupported op -> legacy
	}

	if !config.GlobalConfig.LiteScheduler.Enable {
		return nil, false
	}

	switch op {
	case "acquire":
		sessionID, sessionCtxID, sessionTTL, concurrency := extractSessionDetails(extraData)
		funcKey := targetName
		if !ls.isFuncEnabled(funcKey) {
			return nil, false // 3: whitelist
		}
		sessionCtxEnabled := false
		if sessionCtxID != "" && ls.funcSpecGetter != nil {
			funcSpec := ls.funcSpecGetter(funcKey)
			sessionCtxEnabled = funcSpec != nil && funcSpec.ExtendedMetaData.EnableSessionCtx
		}
		if sessionID == "" && !sessionCtxEnabled {
			return nil, false // non-session call chain -> legacy
		}
		logger.Debug("lite parseRequest acquire enters lite branch", traceField, zap.String("funcKey", funcKey))
		return &LiteRequest{
			Op: op, FuncKey: funcKey, SessionID: sessionID, SessionCtxID: sessionCtxID,
			SessionTTL:  sessionTTL,
			Concurrency: concurrency,
			TenantID:    splitFuncKey(funcKey).tenantID,
			ExtraData:   extraData, TraceID: traceID,
		}, true
	case "release", "retain":
		if !IsLiteAllocationID(targetName) {
			return nil, false // 4e: non-lite prefix -> legacy
		}
		logger.Debug("lite parseRequest enters lite branch", traceField, zap.String("operation", string(op)),
			zap.String("allocationID", targetName))
		return &LiteRequest{
			Op: op, AllocationIDs: []string{targetName},
			ExtraData: extraData, MetricsData: extraData,
			TraceID: traceID, NeedReverseLookup: true,
		}, true
	case "batchRetain":
		ids := strings.Split(targetName, ",")
		liteCount := 0
		for _, id := range ids {
			if IsLiteAllocationID(id) {
				liteCount++
			}
		}
		if liteCount == 0 {
			return nil, false // all non-lite -> legacy
		}
		if liteCount != len(ids) {
			logger.Warn("batchRetain mixed lite/non-lite prefix, fallback to legacy", traceField,
				zap.String("target", targetName))
			return nil, false // 4f: mixed -> legacy
		}
		logger.Debug("lite parseRequest batchRetain enters lite branch", traceField,
			zap.Int("allocationCount", len(ids)))
		return &LiteRequest{
			Op: op, AllocationIDs: ids,
			MetricsData: extraData, TraceID: traceID,
			NeedReverseLookup: true,
		}, true
	}
	return nil, false
}

func extractSessionCtxID(extraData []byte) string {
	_, sessionCtxID, _, _ := extractSessionDetails(extraData)
	return sessionCtxID
}

// extractSessionConfig parses extraData for InstanceSessionConfig (key constant.InstanceSessionConfig).
// Returns sessionID, sessionTTL (seconds) and concurrency. sessionID is "" if absent.
func extractSessionConfig(extraData []byte) (sessionID string, sessionTTL int, concurrency int) {
	sessionID, _, sessionTTL, concurrency = extractSessionDetails(extraData)
	return
}

// extractSessionDetails decodes the outer extraData map once. Acquire and
// reacquire need both session and session-context fields; decoding them in two
// helpers doubled the transient JSON maps on these high-frequency paths.
func extractSessionDetails(extraData []byte) (sessionID, sessionCtxID string, sessionTTL, concurrency int) {
	if len(extraData) == 0 {
		return "", "", 0, 0
	}
	m := map[string][]byte{}
	if err := json.Unmarshal(extraData, &m); err != nil {
		log.GetLogger().Debugf("lite extractSessionConfig: extraData unmarshal failed: %v", err)
		return "", "", 0, 0
	}
	sessionCtxID = string(m[constant.SessionCtxID])
	raw, exists := m[constant.InstanceSessionConfig]
	if !exists {
		return "", sessionCtxID, 0, 0
	}
	sess := commonTypes.InstanceSessionConfig{}
	if err := json.Unmarshal(raw, &sess); err != nil {
		log.GetLogger().Debugf("lite extractSessionConfig: InstanceSessionConfig unmarshal failed: %v", err)
		return "", sessionCtxID, 0, 0
	}
	return sess.SessionID, sessionCtxID, sess.SessionTTL, sess.Concurrency
}
