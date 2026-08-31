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
	"time"

	"go.uber.org/zap"
	"yuanrong.org/kernel/pkg/common/faas_common/constant"
	"yuanrong.org/kernel/pkg/common/faas_common/logger/log"
	"yuanrong.org/kernel/pkg/common/faas_common/statuscode"
	commonTypes "yuanrong.org/kernel/pkg/common/faas_common/types"
	"yuanrong.org/kernel/pkg/functionscaler/config"
	"yuanrong.org/kernel/pkg/functionscaler/selfregister"
	"yuanrong.org/kernel/pkg/functionscaler/session"
	"yuanrong.org/kernel/pkg/functionscaler/types"
)

const (
	// waitForInstance 轮询间隔。
	litePollInterval = 50 * time.Millisecond

	minConcurrency = 1
)

// liteTTL 返回租约有效期，不低于 MinLeaseInterval。
func liteTTL() time.Duration {
	ttl := time.Duration(config.GlobalConfig.LeaseSpan) * time.Millisecond
	if ttl < types.MinLeaseInterval {
		return types.MinLeaseInterval
	}
	return ttl
}

// liteSuccessResp 构建成功响应。
func liteSuccessResp(slot *LiteInstance, allocID, funcKey string, startTime time.Time) *commonTypes.InstanceResponse {
	resp := &commonTypes.InstanceResponse{
		InstanceAllocationInfo: commonTypes.InstanceAllocationInfo{
			ThreadID:      allocID,
			LeaseInterval: int64(liteTTL().Milliseconds()),
		},
		ErrorCode:     constant.InsReqSuccessCode,
		ErrorMessage:  constant.InsReqSuccessMessage,
		SchedulerTime: time.Since(startTime).Seconds(),
	}
	if slot != nil {
		resp.InstanceAllocationInfo.FuncKey = funcKey
		resp.InstanceAllocationInfo.FuncSig = slot.FuncSig
		resp.InstanceAllocationInfo.InstanceID = slot.InstanceID
		resp.InstanceAllocationInfo.InstanceIP = slot.InstanceIP
		resp.InstanceAllocationInfo.InstancePort = slot.InstancePort
		resp.InstanceAllocationInfo.NodeIP = slot.NodeIP
		resp.InstanceAllocationInfo.NodePort = slot.NodePort
		resp.InstanceAllocationInfo.FunctionProxyID = slot.FunctionProxyID
		resp.InstanceAllocationInfo.RouteAddress = slot.RouteAddress
	}
	return resp
}

// liteErrResp 构建错误响应。
func liteErrResp(code int, msg string, startTime time.Time) *commonTypes.InstanceResponse {
	return &commonTypes.InstanceResponse{
		ErrorCode:     code,
		ErrorMessage:  msg,
		SchedulerTime: time.Since(startTime).Seconds(),
	}
}

// reacquireParams 保存 retain-reacquire 解析后的参数。
type reacquireParams struct {
	allocID      string
	sessionID    string
	sessionCtxID string
	sessionTTL   int
	concurrency  int
	funcKey      string
	tenantID     string
	instanceID   string
}

// sessionLookup 封装会话绑定查找结果，减少方法间透传的散装参数。
type sessionLookup struct {
	key     string          // 绑定键
	binding *sessionBinding // 绑定值，不存在时为 nil
	exists  bool            // 是否在 sessions map 中找到
}

func (ls *LiteScheduler) getPool(funcKey string) *LiteFunctionPool {
	ls.poolsMu.RLock()
	defer ls.poolsMu.RUnlock()
	return ls.pools[funcKey]
}

// handleAcquire 处理 acquire 请求，依次尝试：本地粘性 → 外部存储恢复 → 调度 → 冷启动。
func (ls *LiteScheduler) handleAcquire(req *LiteRequest) *commonTypes.InstanceResponse {
	req.ensureReqContext()
	pool, resp := ls.checkHandleAcquireReq(req)
	if resp != nil {
		return resp
	}
	// 阶段1: 计算绑定键并在 req 上缓存一次（依赖 pool.funcSpec.EnableSessionCtx，
	// 在 pool.RLock 下快照，排除 upsertPool 的 funcSpec 换指针），后续所有阶段复用。
	pool.RLock()
	req.bindingKey = pool.sessionBindingKey(req.SessionID, req.SessionCtxID)
	pool.RUnlock()
	req.logger = req.logger.With(zap.String("sessionID", req.bindingKey))
	if resp := ls.tryLocalSticky(pool, req); resp != nil {
		return resp
	}
	// 阶段2: 查询外部存储（不持锁）。
	var storeRec *session.StoreRecord
	if pool.sessionStore != nil {
		var err error
		storeRec, err = pool.sessionStore.getSessionFromStore(req.bindingKey)
		if err != nil {
			req.logger.Debugf("lite acquire get session from store failed: %v", err)
		}
	}
	// 阶段3+4: 重试粘性/存储恢复/调度/冷启动。
	return ls.acquireDispatchOrColdStart(pool, req, storeRec)
}

// checkHandleAcquireReq 处理 acquire 请求拿取 pool 前的一些预校验和处理
func (ls *LiteScheduler) checkHandleAcquireReq(req *LiteRequest) (*LiteFunctionPool,
	*commonTypes.InstanceResponse) {
	if req.SessionTTL < 0 {
		req.logger.Warnf("lite acquire sessionTTL invalid: %d (must be >= 0)", req.SessionTTL)
		return nil, liteErrResp(statuscode.InstanceSessionInvalidErrCode, "sessionTTL must not be negative",
			req.startTime)
	}
	pool := ls.getPool(req.FuncKey)
	if pool == nil {
		req.logger.Warnf("lite acquire pool not found, func not deployed or pool not synced yet")
		return nil, liteErrResp(statuscode.FuncMetaNotFoundErrCode, statuscode.FuncMetaNotFoundErrMsg, req.startTime)
	}
	if errResp := ls.checkConcurrencyLimit(req, pool, req.Concurrency); errResp != nil {
		return nil, errResp
	}
	return pool, nil
}

// checkConcurrencyLimit 校验请求并发度是否超过函数实例上限。
// 实例上限经 pool.RLock 快照读取：upsertPool 在 pool.Lock 下换 funcSpec 指针，
// 无锁读取会与换指针并发构成数据竞争。两个调用方（checkHandleAcquireReq、
// reacquireAllocation）调用时均未持有 pool 锁，自取 RLock 安全。
func (ls *LiteScheduler) checkConcurrencyLimit(req *LiteRequest, pool *LiteFunctionPool,
	concurrency int) *commonTypes.InstanceResponse {
	if limit := pool.instanceConcurrentNum(); limit > 0 && concurrency > limit {
		req.logger.Warnf("lite acquire concurrency %d exceeds function concurrentNum %d", concurrency, limit)
		return liteErrResp(statuscode.InstanceSessionInvalidErrCode,
			"concurrency exceeds function concurrentNum", req.startTime)
	}
	if concurrency < minConcurrency {
		req.logger.Errorf("lite acquire concurrency less than %d", minConcurrency)
		return liteErrResp(statuscode.InstanceSessionInvalidErrCode,
			"concurrency less than minimum value", req.startTime)
	}
	return nil
}

// tryLocalSticky 在 pool.Lock 下尝试本地粘性命中，命中返回响应，未命中返回 nil。
func (ls *LiteScheduler) tryLocalSticky(pool *LiteFunctionPool, req *LiteRequest) *commonTypes.InstanceResponse {
	pool.Lock()
	defer pool.Unlock()
	slot, binding, hit := pool.tryLocalStickyLocked(req.bindingKey)
	if !hit {
		return nil
	}
	resp := ls.assignInstance(pool, req, slot, binding)
	req.logger.Debugf("lite acquire session sticky hit: instance %s (inUse %d/%d, reserved %d)",
		slot.InstanceID, slot.InUse, slot.Capacity, binding.reserved)
	return resp
}

// acquireDispatchOrColdStart 是 handleAcquire 的阶段3+4:
// 重试粘性 → 存储恢复 → 调度 → 冷启动。
func (ls *LiteScheduler) acquireDispatchOrColdStart(pool *LiteFunctionPool, req *LiteRequest,
	storeRec *session.StoreRecord) *commonTypes.InstanceResponse {
	pool.Lock()
	// 阶段3a: 二次粘性检查（阶段2期间可能有并发绑定）。
	if slot, binding, hit := pool.tryLocalStickyLocked(req.bindingKey); hit {
		resp := ls.assignInstance(pool, req, slot, binding)
		req.logger.Debugf("lite acquire session sticky hit: instance %s (inUse %d/%d, reserved %d)",
			slot.InstanceID, slot.InUse, slot.Capacity, binding.reserved)
		pool.Unlock()
		return resp
	}
	// 阶段3b: 尝试从存储指定的实例恢复（崩溃恢复）。
	if resp := ls.tryStoreRecoveryLocked(pool, req, storeRec); resp != nil {
		pool.Unlock()
		return resp
	}
	// 阶段3c: 正常调度。
	if resp := ls.tryDispatchLocked(pool, req); resp != nil {
		pool.Unlock()
		return resp
	}
	// 阶段4: 冷启动。快照 instanceCount 后释放锁。
	instanceCount := len(pool.instances)
	pool.Unlock()
	req.logger.Infof("lite acquire cold start: no schedulable slot (%d instances), wait for scale", instanceCount)
	return ls.handleColdStart(pool, req)
}

// tryStoreRecoveryLocked 尝试用存储记录恢复实例。成功返回响应，否则返回 nil。
// 调用方须持有 pool.Lock。
func (ls *LiteScheduler) tryStoreRecoveryLocked(pool *LiteFunctionPool, req *LiteRequest,
	storeRec *session.StoreRecord) *commonTypes.InstanceResponse {
	if storeRec == nil || storeRec.InstanceID == "" {
		return nil
	}
	slot := pool.instances[storeRec.InstanceID]
	if slot != nil &&
		(slot.Status == InstanceStatusRunning || slot.Status == InstanceStatusSubHealth) &&
		slot.Capacity-slot.InUse >= req.Concurrency && slot.SessionCtxID == req.SessionCtxID {
		req.logger.Debugf("lite acquire session recovered from store: instance %s", storeRec.InstanceID)
		return ls.assignInstance(pool, req, slot, nil)
	}
	// 存储记录已过期，删除防止重复尝试。
	pool.sessionStore.deleteSessionFromStore(req.bindingKey)
	req.logger.Infof("lite acquire store designate instance %s invalid, redispatch", storeRec.InstanceID)
	return nil
}

// tryDispatchLocked 从候选槽位中调度实例。成功返回响应，否则返回 nil。
// 调用方须持有 pool.Lock。
func (ls *LiteScheduler) tryDispatchLocked(pool *LiteFunctionPool, req *LiteRequest) *commonTypes.InstanceResponse {
	slots := pool.candidateSlotsLocked(req.SessionCtxID, req.Concurrency)
	chosen := pool.dispatcher.Select(slots, req.Concurrency)
	if chosen == nil {
		return nil
	}
	req.logger.Debugf("lite acquire dispatched: instance %s (inUse %d/%d, %d candidates)",
		chosen.InstanceID, chosen.InUse+req.Concurrency, chosen.Capacity, len(slots))
	return ls.assignInstance(pool, req, chosen, nil)
}

// assignInstance 在给定 slot 上创建分配。
// binding != nil 表示粘性命中，从预留中扣减；为 nil 则新建绑定或走无会话模式。
// 调用方须持有 pool.Lock。
func (ls *LiteScheduler) assignInstance(pool *LiteFunctionPool, req *LiteRequest, slot *LiteInstance,
	binding *sessionBinding) *commonTypes.InstanceResponse {
	pool.seqCounter++
	seq := int(pool.seqCounter)
	allocID := genAllocationID(req.bindingKey, slot.InstanceID, seq)

	ls.applySlotBinding(pool, req, slot, binding)

	alloc := &Allocation{
		AllocationID: allocID,
		SessionID:    req.SessionID,
		SessionCtxID: req.SessionCtxID,
		SessionTTL:   req.SessionTTL,
		TenantID:     req.TenantID,
		InstanceID:   slot.InstanceID,
		FuncKey:      req.FuncKey,
		ExpireAt:     time.Now().Add(liteTTL()),
		CreatedAt:    time.Now(),
	}
	ls.allocMu.Lock()
	ls.allocations[allocID] = alloc
	ls.allocMu.Unlock()

	ls.registerExpiryTask(allocID)
	ls.recordAcquireMetrics(pool, req)
	return liteSuccessResp(slot, allocID, req.FuncKey, req.startTime)
}

// applySlotBinding 根据会话状态更新 slot.InUse 和绑定关系。
// 调用方须持有 pool.Lock。
func (ls *LiteScheduler) applySlotBinding(pool *LiteFunctionPool, req *LiteRequest, slot *LiteInstance,
	binding *sessionBinding) {
	if binding != nil {
		// 粘性命中: 从预留中扣减（或超额获取）。
		slot.InUse += pool.bindSessionStickyTakeLocked(binding)
	} else if req.SessionID != "" {
		// 新绑定: 预留 concurrency 个单位。
		slot.InUse += req.Concurrency
		pool.bindSessionFreshLocked(req.bindingKey, slot.InstanceID, req.Concurrency)
		pool.sessionStore.saveSessionToStore(req.bindingKey, slot.InstanceID, req)
	} else {
		// 无会话: 1 单位模式。
		slot.InUse++
	}
}

// recordAcquireMetrics 记录 acquire 成功指标。
func (ls *LiteScheduler) recordAcquireMetrics(pool *LiteFunctionPool, req *LiteRequest) {
	if ls.metrics == nil {
		return
	}
	policy := "unknown"
	if pool.dispatcher != nil {
		policy = pool.dispatcher.Policy()
	}
	ls.metrics.incAcquire(req.FuncKey, req.TenantID, policy, "success")
}

// handleRelease 处理 release 请求，释放分配并归还实例容量。
func (ls *LiteScheduler) handleRelease(req *LiteRequest) *commonTypes.InstanceResponse {
	req.ensureReqContext()
	req.logger = req.logger.With(zap.String("allocID", req.AllocationIDs[0]))
	ls.allocMu.Lock()
	alloc, ok := ls.allocations[req.AllocationIDs[0]]
	if !ok {
		ls.allocMu.Unlock()
		req.logger.Warnf("lite release allocation not found, lease expired or already released")
		return liteErrResp(statuscode.InstanceNotFoundErrCode, statuscode.InstanceNotFoundErrMsg, req.startTime)
	}
	delete(ls.allocations, req.AllocationIDs[0])
	ls.allocMu.Unlock()
	// release 的 funcKey 由分配解析后方可知（入口尚未知，无法烧入基座），此处附加。
	req.logger = req.logger.With(zap.String("funcKey", alloc.FuncKey))

	ls.removeExpiryTask(req.AllocationIDs[0])
	slot, pool := ls.releaseInPool(req, alloc)
	if ls.metrics != nil {
		policy := "unknown"
		if pool != nil && pool.dispatcher != nil {
			policy = pool.dispatcher.Policy()
		}
		ls.metrics.incRelease(alloc.FuncKey, alloc.TenantID, policy, "success")
	}
	return liteSuccessResp(slot, alloc.AllocationID, alloc.FuncKey, req.startTime)
}

// releaseInPool 将容量归还到池中。有会话绑定时归还到预留池，无会话时直接归还实例。
// 调用方不得持有 pool.Lock。
func (ls *LiteScheduler) releaseInPool(req *LiteRequest, alloc *Allocation) (*LiteInstance, *LiteFunctionPool) {
	logger := req.logger.With(zap.String("allocID", alloc.AllocationID),
		zap.String("instanceID", alloc.InstanceID))
	pool := ls.getPool(alloc.FuncKey)
	if pool == nil {
		logger.Infof("lite release pool gone (func undeployed), allocation %s cleaned", alloc.AllocationID)
		return nil, nil
	}
	needUnbindTimer, unbindSessionID := ls.releaseSlotLocked(pool, alloc)
	slot := ls.snapshotSlot(req, pool, alloc.InstanceID)
	if needUnbindTimer {
		ls.startSessionUnbindTimer(pool, unbindSessionID, alloc.SessionTTL)
	}
	return slot, pool
}

// releaseSlotLocked 在 pool.Lock 下归还容量，返回是否需要启动解绑定时器。
// 注意：会话分配不在此处递减 slot.InUse——容量归还到会话预留（unbindSessionOnRelease
// 中 reserved++），会话占用的份额（reserved+activeAllocs）延迟到会话解绑
// （removeSessionBinding）时才释放回实例，以保证 idle TTL 内的粘性容量独占。
// 在此处额外 s.InUse-- 会与解绑时的释放双重计数，导致 InUse 偏低、容量超卖。
func (ls *LiteScheduler) releaseSlotLocked(pool *LiteFunctionPool, alloc *Allocation) (bool, string) {
	pool.Lock()
	defer pool.Unlock()
	s := pool.instances[alloc.InstanceID]
	if s == nil {
		return false, ""
	}
	if alloc.SessionID != "" {
		sessionKey := pool.sessionBindingKey(alloc.SessionID, alloc.SessionCtxID)
		needTimer, _ := pool.unbindSessionOnRelease(sessionKey)
		return needTimer, sessionKey
	}
	if s.InUse > 0 {
		s.InUse--
	}
	return false, ""
}

// snapshotSlot 在 pool.RLock 下读取 slot 快照并记录日志。
func (ls *LiteScheduler) snapshotSlot(req *LiteRequest, pool *LiteFunctionPool, instanceID string) *LiteInstance {
	pool.RLock()
	slot := pool.instances[instanceID]
	if slot != nil {
		req.logger.Debugf("lite release: instance %s (inUse %d/%d)", instanceID, slot.InUse, slot.Capacity)
	}
	pool.RUnlock()
	return slot
}

// startSessionUnbindTimer 在 sessionTTL 后移除会话绑定（空闲解绑）。
// 如果绑定已被取消或有新请求到达，定时器会安全跳过。
func (ls *LiteScheduler) startSessionUnbindTimer(pool *LiteFunctionPool, sessionID string, sessionTTL int) {
	ttl := sessionTTLFor(sessionTTL)
	pool.Lock()
	binding, ok := pool.sessions[sessionID]
	if !ok || !binding.expiring || binding.activeAllocs != 0 {
		pool.Unlock()
		return
	}
	binding.stopTimer()
	var timer *time.Timer
	timer = time.AfterFunc(ttl, func() {
		ls.fireSessionUnbind(pool, sessionID, binding, timer)
	})
	binding.timer = timer
	pool.Unlock()
}

// fireSessionUnbind 是 idle-unbind 定时器回调，在 pool.Lock 下安全移除过期绑定。
// 异步回调：原请求已结束拿不到 req，本地构造 logger（带 sessionID/funcKey）。
func (ls *LiteScheduler) fireSessionUnbind(pool *LiteFunctionPool, sessionID string, binding *sessionBinding,
	timer *time.Timer) {
	logger := log.GetLogger().With(zap.String("sessionID", sessionID), zap.String("funcKey", pool.funcKey))
	pool.Lock()
	current, exists := pool.sessions[sessionID]
	if !exists || current != binding || current.timer != timer ||
		!current.expiring || current.activeAllocs != 0 {
		pool.Unlock()
		return
	}
	funcKey := pool.funcKey
	pool.removeSessionBinding(sessionID)
	pool.Unlock()
	logger.Infof("lite session idle-unbind: session %s unbound after TTL (func %s)", sessionID, funcKey)
}

// handleRetain 处理单个 retain 请求：解析 metrics 后委托给 handleRetainWithMetrics。
func (ls *LiteScheduler) handleRetain(req *LiteRequest) *commonTypes.InstanceResponse {
	req.ensureReqContext()
	var metrics *types.InstanceThreadMetrics
	if len(req.MetricsData) != 0 {
		metrics = &types.InstanceThreadMetrics{}
		if err := json.Unmarshal(req.MetricsData, metrics); err != nil {
			req.logger.Warnf("lite retain metrics unmarshal failed: %v", err)
			metrics = nil
		}
	}
	return ls.handleRetainWithMetrics(req, metrics)
}

// handleRetainWithMetrics 刷新已有分配的租约，丢失时通过 ReacquireData 重建。
func (ls *LiteScheduler) handleRetainWithMetrics(req *LiteRequest,
	metrics *types.InstanceThreadMetrics) *commonTypes.InstanceResponse {
	req.logger = req.logger.With(zap.String("allocID", req.AllocationIDs[0]))
	allocID := req.AllocationIDs[0]

	// (1) 查找分配，快照关键字段后释放锁。
	ls.allocMu.Lock()
	alloc, ok := ls.allocations[allocID]
	if !ok {
		ls.allocMu.Unlock()
		return ls.reacquireAllocation(req, metrics)
	}
	funcKey, instanceID := alloc.FuncKey, alloc.InstanceID
	ls.allocMu.Unlock()
	// retain（单个或 batch 子请求）的 funcKey 由分配解析后方可知，此处附加；
	// 查找失败走 reacquireAllocation，由其附加 ReacquireData 解析出的 funcKey。
	req.logger = req.logger.With(zap.String("funcKey", funcKey))

	if req.NeedReverseLookup && !ls.isFuncEnabled(funcKey) {
		req.logger.Warnf("lite retain func %s is no longer enabled", funcKey)
		return liteErrResp(statuscode.FuncMetaNotFoundErrCode, statuscode.FuncMetaNotFoundErrMsg, req.startTime)
	}

	// (2) 校验 pool 和 slot。
	pool, slot, errResp := ls.validateRetainTarget(req, allocID, funcKey, instanceID)
	if errResp != nil {
		return errResp
	}

	// (3) 刷新 TTL。
	return ls.refreshRetainTTL(req, allocID, pool, slot)
}

// validateRetainTarget 校验 retain 的目标 pool 和实例是否有效，无效时清理分配。
func (ls *LiteScheduler) validateRetainTarget(req *LiteRequest, allocID, funcKey, instanceID string) (*LiteFunctionPool,
	*LiteInstance, *commonTypes.InstanceResponse) {
	pool := ls.getPool(funcKey)
	if pool == nil {
		ls.deleteAllocAndExpiry(allocID)
		req.logger.Infof("lite retain pool gone (func %s undeployed), allocation dropped", funcKey)
		return nil, nil, liteErrResp(constant.LeaseExpireOrDeletedErrorCode,
			constant.LeaseExpireOrDeletedErrorMessage, req.startTime)
	}
	pool.RLock()
	slot := pool.instances[instanceID]
	pool.RUnlock()
	if slot == nil || slot.Status == InstanceStatusUnavailable {
		ls.deleteAllocAndExpiry(allocID)
		req.logger.Warnf("lite retain instance %s absent or unhealthy, allocation dropped", instanceID)
		return nil, nil, liteErrResp(statuscode.InstanceStatusAbnormalCode,
			constant.LeaseErrorInstanceIsAbnormalMessage, req.startTime)
	}
	return pool, slot, nil
}

// refreshRetainTTL 刷新分配的过期时间并记录指标。
func (ls *LiteScheduler) refreshRetainTTL(req *LiteRequest, allocID string, pool *LiteFunctionPool,
	slot *LiteInstance) *commonTypes.InstanceResponse {
	ls.allocMu.Lock()
	alloc, ok := ls.allocations[allocID]
	if !ok {
		ls.allocMu.Unlock()
		req.logger.Warnf("lite retain lost lease between lookup and refresh (concurrent release)")
		return liteErrResp(statuscode.LeaseIDNotFoundCode, statuscode.LeaseIDNotFoundMsg, req.startTime)
	}
	alloc.ExpireAt = time.Now().Add(liteTTL())
	newExpire := alloc.ExpireAt
	ls.allocMu.Unlock()

	ls.updateExpiryTask(allocID)
	ls.recordRetainSuccess(pool, alloc)
	req.logger.Debugf("lite retain refreshed: instance %s, new expiry %s",
		alloc.InstanceID, newExpire.Format(time.RFC3339Nano))
	return liteSuccessResp(slot, alloc.AllocationID, alloc.FuncKey, req.startTime)
}

// deleteAllocAndExpiry 清理分配记录和过期任务。
func (ls *LiteScheduler) deleteAllocAndExpiry(allocID string) {
	ls.allocMu.Lock()
	delete(ls.allocations, allocID)
	ls.allocMu.Unlock()
	ls.removeExpiryTask(allocID)
}

// reacquireAllocation 从 retain 请求的 ReacquireData 重建丢失的分配。
func (ls *LiteScheduler) reacquireAllocation(req *LiteRequest,
	metrics *types.InstanceThreadMetrics) *commonTypes.InstanceResponse {
	params, errResp := ls.validateReacquireRequest(req, metrics)
	if errResp != nil {
		return errResp
	}
	// 恢复路径的 funcKey 来自 ReacquireData（入口与 reverseLookup 均不可知），解析后附加。
	req.logger = req.logger.With(zap.String("funcKey", params.funcKey))
	// 查找 pool/实例/绑定，创建分配并更新 InUse。调用方不得持有任何锁。
	pool := ls.getPool(params.funcKey)
	if pool == nil {
		req.logger.Warnf("lite retain reacquire pool not found")
		return liteErrResp(statuscode.FuncMetaNotFoundErrCode, statuscode.FuncMetaNotFoundErrMsg, req.startTime)
	}
	// 与 handleAcquire 一致：在调度前校验并发度上下界，避免 concurrency<=0
	// 进入 buildReacquiredAlloc 后导致 slot.InUse 统计错乱（0 不增、负数反减）
	// 以及 bindSessionFreshLocked 的 reserved=concurrency-1 出现非法负值。
	if errResp := ls.checkConcurrencyLimit(req, pool, params.concurrency); errResp != nil {
		return errResp
	}
	pool.Lock()
	slot, lookup, errResp := ls.checkReacquireSlotLocked(req, pool, params)
	if errResp != nil {
		pool.Unlock()
		return errResp
	}
	// 幂等：防止并发 retain 重复计数。
	now := time.Now()
	ls.allocMu.Lock()
	if alloc, exists := ls.allocations[params.allocID]; exists {
		alloc.ExpireAt = now.Add(liteTTL())
		ls.allocMu.Unlock()
		pool.Unlock()
		ls.updateExpiryTask(params.allocID)
		ls.recordRetainSuccess(pool, alloc)
		req.logger.Infof("lite retain reacquire raced with another recovery, refreshed existing allocation")
		return liteSuccessResp(slot, alloc.AllocationID, alloc.FuncKey, req.startTime)
	}
	alloc := ls.buildReacquiredAlloc(pool, slot, params, &lookup, now)
	overCapacity := slot.InUse > slot.Capacity
	newInUse, capacity := slot.InUse, slot.Capacity
	ls.allocMu.Unlock()
	pool.Unlock()
	ls.updateExpiryTask(params.allocID)
	ls.recordRetainSuccess(pool, alloc)
	if overCapacity {
		req.logger.Warnf("lite retain reacquired allocation over capacity: instance %s inUse %d/%d",
			params.instanceID, newInUse, capacity)
	} else {
		req.logger.Infof("lite retain reacquired allocation: instance %s inUse %d/%d",
			params.instanceID, newInUse, capacity)
	}
	return liteSuccessResp(slot, params.allocID, params.funcKey, req.startTime)
}

// validateReacquireRequest 校验 reacquire 参数，成功返回解析后的参数，失败返回错误响应。
func (ls *LiteScheduler) validateReacquireRequest(req *LiteRequest,
	metrics *types.InstanceThreadMetrics) (*reacquireParams, *commonTypes.InstanceResponse) {
	allocID := req.AllocationIDs[0]
	if metrics == nil || len(metrics.ReacquireData) == 0 {
		req.logger.Warnf("lite retain allocation not found and reacquireData is empty")
		return nil, liteErrResp(statuscode.LeaseIDNotFoundCode, statuscode.LeaseIDNotFoundMsg, req.startTime)
	}
	isLite, expectedSessionHash, instanceID, _ := parseLiteAllocationID(allocID)
	if !isLite {
		req.logger.Warnf("lite retain reacquire allocation ID is invalid")
		return nil, liteErrResp(statuscode.LeaseIDIllegalCode, statuscode.LeaseIDIllegalMsg, req.startTime)
	}
	sessionID, sessionCtxID, sessionTTL, concurrency := extractSessionDetails(metrics.ReacquireData)
	if errResp := ls.validateSessionAndOwner(req, sessionCheckParams{
		sessionID:    sessionID,
		sessionCtxID: sessionCtxID,
		sessionTTL:   sessionTTL,
		expectedHash: expectedSessionHash,
		funcKey:      metrics.FunctionKey,
	}); errResp != nil {
		return nil, errResp
	}
	return &reacquireParams{
		allocID:      allocID,
		sessionID:    sessionID,
		sessionCtxID: sessionCtxID,
		sessionTTL:   sessionTTL,
		concurrency:  concurrency,
		funcKey:      metrics.FunctionKey,
		tenantID:     splitFuncKey(metrics.FunctionKey).tenantID,
		instanceID:   instanceID,
	}, nil
}

// sessionCheckParams 封装 validateSessionAndOwner 的入参，避免加 req 后参数超过 5 个。
type sessionCheckParams struct {
	sessionID    string
	sessionCtxID string
	sessionTTL   int
	expectedHash string
	funcKey      string
}

// validateSessionAndOwner 校验会话配置、哈希一致性、函数可用性和 owner 归属。
func (ls *LiteScheduler) validateSessionAndOwner(req *LiteRequest, p sessionCheckParams) *commonTypes.InstanceResponse {
	if (p.sessionID == "" && p.sessionCtxID == "") || p.sessionTTL < 0 {
		req.logger.Warnf("lite retain reacquire session config invalid: empty=%t, sessionTTL=%d",
			p.sessionID == "" && p.sessionCtxID == "", p.sessionTTL)
		return liteErrResp(statuscode.InstanceSessionInvalidErrCode, "session config invalid", req.startTime)
	}
	if sessionHash(allocationSessionID(p.sessionID, p.sessionCtxID)) != p.expectedHash {
		req.logger.Warnf("lite retain reacquire session hash does not match allocation ID")
		return liteErrResp(statuscode.LeaseIDIllegalCode, statuscode.LeaseIDIllegalMsg, req.startTime)
	}
	if p.funcKey == "" || !ls.isFuncEnabled(p.funcKey) {
		req.logger.Warnf("lite retain reacquire function %s is missing or not enabled", p.funcKey)
		return liteErrResp(statuscode.FuncMetaNotFoundErrCode, statuscode.FuncMetaNotFoundErrMsg, req.startTime)
	}
	if ls.ownerProxy != nil {
		tenantID := splitFuncKey(p.funcKey).tenantID
		ownerID, owned := ls.ownerProxy.CheckHashOwner(
			schedulerOwnerKey(tenantID, p.funcKey, p.sessionID, p.sessionCtxID))
		if !owned {
			req.logger.Warnf("lite retain reacquire is not session owner, reroute to %s", ownerID)
			return liteErrResp(statuscode.AcquireNonOwnerSchedulerErrorCode, ownerID, req.startTime)
		}
	}
	return nil
}

// checkReacquireSlotLocked 校验实例和会话绑定。
// 成功返回 (slot, lookup, nil)；失败返回 (nil, _, errResp)，调用方须释放 pool.Lock。
func (ls *LiteScheduler) checkReacquireSlotLocked(req *LiteRequest, pool *LiteFunctionPool,
	params *reacquireParams) (*LiteInstance, sessionLookup, *commonTypes.InstanceResponse) {
	slot := pool.instances[params.instanceID]
	if slot == nil || (slot.FuncKey != "" && slot.FuncKey != params.funcKey) {
		req.logger.Warnf("lite retain reacquire instance %s not found in function pool", params.instanceID)
		return nil, sessionLookup{}, liteErrResp(statuscode.InstanceNotFoundErrCode,
			statuscode.InstanceNotFoundErrMsg, req.startTime)
	}
	if slot.Status == InstanceStatusUnavailable {
		req.logger.Warnf("lite retain reacquire instance %s is unavailable", params.instanceID)
		return nil, sessionLookup{}, liteErrResp(statuscode.InstanceStatusAbnormalCode,
			constant.LeaseErrorInstanceIsAbnormalMessage, req.startTime)
	}
	key := pool.sessionBindingKey(params.sessionID, params.sessionCtxID)
	binding, exists := pool.sessions[key]
	if params.sessionID != "" && exists && binding.instanceID != params.instanceID {
		req.logger.Warnf("lite retain reacquire session already bound to instance %s, requested %s",
			binding.instanceID, params.instanceID)
		return nil, sessionLookup{}, liteErrResp(statuscode.InstanceSessionInvalidErrCode,
			"session is bound to a different instance", req.startTime)
	}
	return slot, sessionLookup{key: key, binding: binding, exists: exists}, nil
}

// buildReacquiredAlloc 构建重新获取的分配，更新 InUse 和绑定关系。
// 调用方须持有 pool.Lock 和 allocMu.Lock。
func (ls *LiteScheduler) buildReacquiredAlloc(pool *LiteFunctionPool, slot *LiteInstance, params *reacquireParams,
	lookup *sessionLookup, now time.Time) *Allocation {
	if ls.allocations == nil {
		ls.allocations = make(map[string]*Allocation)
	}
	alloc := &Allocation{
		AllocationID: params.allocID,
		SessionID:    params.sessionID,
		SessionCtxID: params.sessionCtxID,
		SessionTTL:   params.sessionTTL,
		TenantID:     params.tenantID,
		InstanceID:   params.instanceID,
		FuncKey:      params.funcKey,
		ExpireAt:     now.Add(liteTTL()),
		CreatedAt:    now,
	}
	ls.allocations[params.allocID] = alloc

	if params.sessionID != "" {
		if lookup.exists {
			slot.InUse += pool.bindSessionStickyTakeLocked(lookup.binding)
		} else {
			slot.InUse += params.concurrency
			pool.bindSessionFreshLocked(lookup.key, params.instanceID, params.concurrency)
			pool.sessionStore.saveSessionToStore(
				lookup.key,
				params.instanceID,
				&LiteRequest{
					SessionID:    params.sessionID,
					SessionCtxID: params.sessionCtxID,
					SessionTTL:   params.sessionTTL,
					Concurrency:  params.concurrency,
				})
		}
	} else {
		slot.InUse++
	}
	return alloc
}

// recordRetainSuccess 记录 retain 成功指标。
func (ls *LiteScheduler) recordRetainSuccess(pool *LiteFunctionPool, alloc *Allocation) {
	if ls.metrics == nil || alloc == nil {
		return
	}
	policy := "unknown"
	if pool != nil && pool.dispatcher != nil {
		policy = pool.dispatcher.Policy()
	}
	ls.metrics.incRetain(alloc.FuncKey, alloc.TenantID, policy, "success")
}

// handleBatchRetain 批量 retain：逐个委托给 handleRetainWithMetrics。
func (ls *LiteScheduler) handleBatchRetain(req *LiteRequest) *commonTypes.BatchInstanceResponse {
	req.ensureReqContext()
	metricsByAllocation := make(map[string]*types.InstanceThreadMetrics)
	if len(req.MetricsData) != 0 {
		if err := json.Unmarshal(req.MetricsData, &metricsByAllocation); err != nil {
			req.logger.Warnf("lite batchRetain metrics unmarshal failed, err: %v", err)
		}
	}
	resp := &commonTypes.BatchInstanceResponse{
		InstanceAllocSucceed: map[string]commonTypes.InstanceAllocationSucceedInfo{},
		InstanceAllocFailed:  map[string]commonTypes.InstanceAllocationFailedInfo{},
		LeaseInterval:        int64(liteTTL().Milliseconds()),
	}
	for _, allocID := range req.AllocationIDs {
		// 每个子 retain 独占一个 LiteRequest，继承父请求的 logger/startTime。
		// handleRetainWithMetrics 会 .With(allocID) 增强子 logger，不影响父 req.logger。
		sub := &LiteRequest{
			Op: "retain", AllocationIDs: []string{allocID},
			TraceID: req.TraceID, NeedReverseLookup: true,
			logger:    req.logger,
			startTime: req.startTime,
		}
		insResp := ls.handleRetainWithMetrics(sub, metricsByAllocation[allocID])
		if insResp.ErrorCode == constant.InsReqSuccessCode {
			resp.InstanceAllocSucceed[allocID] = commonTypes.InstanceAllocationSucceedInfo{
				FuncKey: insResp.FuncKey, FuncSig: insResp.FuncSig,
				InstanceID: insResp.InstanceID, ThreadID: allocID,
			}
		} else {
			resp.InstanceAllocFailed[allocID] = commonTypes.InstanceAllocationFailedInfo{
				ErrorCode: insResp.ErrorCode, ErrorMessage: insResp.ErrorMessage,
			}
		}
	}
	req.logger.Debugf("lite batchRetain done, succeeded: %d, failed: %d, total: %d", len(resp.InstanceAllocSucceed),
		len(resp.InstanceAllocFailed), len(req.AllocationIDs))
	resp.SchedulerTime = time.Since(req.startTime).Seconds()
	return resp
}

// handleColdStart 发出扩容提示并轮询等待可用实例。
func (ls *LiteScheduler) handleColdStart(pool *LiteFunctionPool, req *LiteRequest) *commonTypes.InstanceResponse {
	if ls.scaleHintSender != nil {
		if errResp := ls.sendScaleHint(pool, req); errResp != nil {
			return errResp
		}
	} else {
		req.logger.Warnf("lite cold start: scaleHintSender is nil, cannot request scale-up")
	}
	if ls.metrics != nil {
		ls.metrics.incScaleHint(req.FuncKey, req.TenantID, "cold_start")
	}
	return ls.waitForInstance(pool, req)
}

// sendScaleHint 发送扩容提示，返回非 nil 表示需提前终止。
func (ls *LiteScheduler) sendScaleHint(pool *LiteFunctionPool, req *LiteRequest) *commonTypes.InstanceResponse {
	req.logger.Infof("lite cold start: emit scale hint (inUse %d, capacity %d, requested %d)",
		pool.currentInUse(), pool.currentCapacity(), req.Concurrency)
	response, sendErr := ls.scaleHintSender.Send(&ScaleHint{
		FuncKey:                 req.FuncKey,
		TenantID:                req.TenantID,
		SessionID:               req.SessionID,
		SessionCtxID:            req.SessionCtxID,
		Reason:                  "cold_start",
		RequestedConcurrency:    req.Concurrency,
		CurrentLocalConcurrency: pool.currentInUse(),
		CurrentLocalCapacity:    pool.currentCapacity(),
		SchedulerID:             selfregister.SelfInstanceID,
		TraceID:                 req.TraceID,
		RequestID:               req.TraceID,
	})
	if sendErr != nil {
		req.logger.Warnf("lite cold start: scale hint failed: %v", sendErr)
	}
	if response != nil && response.ErrorCode != 0 {
		return liteErrResp(response.ErrorCode, response.ErrorMessage, req.startTime)
	}
	return nil
}

// waitForInstance 在 AcquireWaitTimeoutMs 内轮询可用实例。
func (ls *LiteScheduler) waitForInstance(pool *LiteFunctionPool, req *LiteRequest) *commonTypes.InstanceResponse {
	timeout := time.Duration(config.GlobalConfig.LiteScheduler.AcquireWaitTimeoutMs) * time.Millisecond
	if timeout <= 0 {
		req.logger.Warnf("lite waitForInstance: AcquireWaitTimeoutMs<=0, reject immediately")
		return liteErrResp(statuscode.NoInstanceAvailableErrCode, "no available instance", req.startTime)
	}
	deadline := time.Now().Add(timeout)
	ticker := time.NewTicker(litePollInterval)
	defer ticker.Stop()
	for {
		if resp := ls.tryPollDispatch(pool, req); resp != nil {
			return resp
		}
		if time.Now().After(deadline) {
			req.logger.Warnf("lite waitForInstance: timed out after %dms", timeout.Milliseconds())
			return liteErrResp(statuscode.NoInstanceAvailableErrCode, "no available instance", req.startTime)
		}
		select {
		case <-ticker.C:
		case <-ls.stopCh:
			req.logger.Warnf("lite waitForInstance: scheduler stopping, abort wait")
			return liteErrResp(statuscode.NoInstanceAvailableErrCode, "no available instance", req.startTime)
		}
	}
}

// tryPollDispatch 单次轮询尝试调度，成功返回响应，否则返回 nil。
func (ls *LiteScheduler) tryPollDispatch(pool *LiteFunctionPool, req *LiteRequest) *commonTypes.InstanceResponse {
	pool.Lock()
	chosen := pool.dispatcher.Select(pool.candidateSlotsLocked(req.SessionCtxID, req.Concurrency), req.Concurrency)
	if chosen != nil {
		req.logger.Debugf("lite waitForInstance: slot appeared, instance %s", chosen.InstanceID)
		resp := ls.assignInstance(pool, req, chosen, nil)
		pool.Unlock()
		return resp
	}
	pool.Unlock()
	return nil
}
