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
	"time"

	"go.uber.org/zap"
	"yuanrong.org/kernel/pkg/common/faas_common/logger/log"
	commonTypes "yuanrong.org/kernel/pkg/common/faas_common/types"
	"yuanrong.org/kernel/pkg/functionscaler/registry"
	"yuanrong.org/kernel/pkg/functionscaler/types"
	"yuanrong.org/kernel/pkg/functionscaler/utils"
)

const defaultChanSize = 1000

// liteFuncSpecBarrierTimeout is the safety-net timeout for processInstanceEvents
// to wait on funcSpecSyncedDone. The funcSpec Synced event is published during
// ProcessETCDList (startup), so it normally arrives within seconds; this timeout
// guards against a stuck funcSpec etcd watcher or a processFuncSpecEvents exit
// so the lite path can degrade to serving with a potentially incomplete pool
// rather than blocking forever. It is shorter than instanceSyncedWaitTimeout
// (1m in the functionscaler package) so WaitReadyForAcquire's lite instance
// barrier still has room to close before its own timeout fires.
const liteFuncSpecBarrierTimeout = 30 * time.Second

// SubscribeAndLoop registers three independent registry subscriptions and starts event loops.
// It reads ls.stopCh (populated by New) to signal the three loops to exit; the registry
// does not close subscription channels, so without stopCh the loops would leak for the
// lifetime of the process.
func (ls *LiteScheduler) SubscribeAndLoop() {
	ls.funcSpecCh = make(chan registry.SubEvent, defaultChanSize)
	ls.insSpecCh = make(chan registry.SubEvent, defaultChanSize)
	ls.schedulerCh = make(chan registry.SubEvent, defaultChanSize)
	registry.GlobalRegistry.SubscribeFuncSpec(ls.funcSpecCh)
	registry.GlobalRegistry.SubscribeInsSpec(ls.insSpecCh)
	registry.GlobalRegistry.SubscribeSchedulerProxy(ls.schedulerCh)
	go ls.processFuncSpecEvents()
	go ls.processInstanceEvents()
	go ls.processSchedulerEvents()
	go ls.processExpiryEvents()
	go ls.processSessionContextIdle()
}

func (ls *LiteScheduler) processFuncSpecEvents() {
	logger := log.GetLogger()
	// Best-effort close funcSpecSyncedDone on every exit path. funcSpecSyncedOnce
	// makes this idempotent with the explicit close on SubEventTypeSynced below.
	// Without this defer, a closed funcSpecCh would leave funcSpecSyncedDone open
	// and processInstanceEvents would block for the full liteFuncSpecBarrierTimeout
	// on the barrier select before degrading.
	defer ls.funcSpecSyncedOnce.Do(func() { close(ls.funcSpecSyncedDone) })
	for {
		select {
		case <-ls.stopCh:
			logger.Info("lite funcSpec event loop exiting")
			return
		case event, ok := <-ls.funcSpecCh:
			if !ok {
				logger.Warn("lite funcSpec channel closed, event loop exiting")
				return
			}
			// SubEventTypeSynced is a control signal with an empty FuncKey
			// payload (&types.FunctionSpecification{}). Handle it before the
			// isFuncEnabled check so the barrier is closed regardless of the
			// whitelist config (otherwise EnableAllTenants=false would skip
			// the empty FuncKey and the barrier would never close), and before
			// upsertPool so no phantom pool with an empty FuncKey is created.
			// Closing funcSpecSyncedDone unblocks processInstanceEvents which
			// waits on it before consuming any instance event, guaranteeing
			// every initial funcSpec has been upserted into a pool before any
			// instance event is dispatched.
			if event.EventType == registry.SubEventTypeSynced {
				ls.funcSpecSyncedOnce.Do(func() { close(ls.funcSpecSyncedDone) })
				logger.Info("lite funcSpec subscription synced, lite pools ready for instance events")
				continue
			}
			funcSpec, ok := event.EventMsg.(*types.FunctionSpecification)
			if !ok {
				logger.Warnf("lite funcSpec event type assertion failed, skip")
				continue
			}
			if !ls.isFuncEnabled(funcSpec.FuncKey) {
				continue
			}
			switch event.EventType {
			case registry.SubEventTypeUpdate:
				ls.upsertPool(funcSpec)
			case registry.SubEventTypeDelete:
				logger.Infof("lite funcSpec delete: drop pool %s", funcSpec.FuncKey)
				ls.deletePool(funcSpec.FuncKey)
			}
		}
	}
}

func (ls *LiteScheduler) processInstanceEvents() {
	logger := log.GetLogger()
	// Best-effort close insSyncedDone on every exit path (barrier-timeout exit,
	// stopCh, channel closed). insSyncedOnce makes this idempotent with the
	// explicit close on SubEventTypeSynced below. Without this defer, an exit
	// before the synced event arrives would leave insSyncedDone open forever
	// and FaaSScheduler.WaitReadyForAcquire would block for the full deadline.
	defer ls.insSyncedOnce.Do(func() { close(ls.insSyncedDone) })
	// Wait for the funcSpec barrier before consuming any instance event.
	// processFuncSpecEvents and this loop run as independent goroutines; without
	// this wait, an instance event whose funcSpec is still queued in funcSpecCh
	// would hit pool==nil below and be silently dropped (no replay), permanently
	// losing the instance from the lite pool. The instance registry publishes
	// its initial list only after the function registry's initial list has been
	// published (ProcessETCDList is serial), so the funcSpec Synced event is
	// already in funcSpecCh by the time instance events arrive here. The timeout
	// is a safety net for environments where the Synced event never arrives
	// (e.g. funcSpec etcd watcher stuck or processFuncSpecEvents exited); in
	// that case we serve with a potentially incomplete pool rather than
	// blocking forever, matching WaitReadyForAcquire's degradation contract.
	timer := time.NewTimer(liteFuncSpecBarrierTimeout)
	select {
	case <-ls.funcSpecSyncedDone:
		logger.Info("lite funcSpec barrier satisfied, start consuming instance events")
	case <-timer.C:
		logger.Warnf("lite funcSpec barrier timeout, consuming instance events with potentially incomplete pools")
	case <-ls.stopCh:
		logger.Info("lite instance event loop exiting before funcSpec barrier satisfied")
		timer.Stop()
		return
	}
	timer.Stop()
	for {
		select {
		case <-ls.stopCh:
			logger.Info("lite instance event loop exiting")
			return
		case event, ok := <-ls.insSpecCh:
			if !ok {
				logger.Warn("lite instance channel closed, event loop exiting")
				return
			}
			// SubEventTypeSynced is a control signal with no payload dependency.
			// Early-filter it before the type assertion so a malformed or nil
			// EventMsg on the synced event cannot skip close(ls.insSyncedDone),
			// which would leave FaaSScheduler.Recover() waiting the full timeout.
			// LiteScheduler subscribes to InsSpec via its own channel, so it
			// needs its own barrier independent of FaaSScheduler.insSyncedDone.
			if event.EventType == registry.SubEventTypeSynced {
				ls.insSyncedOnce.Do(func() { close(ls.insSyncedDone) })
				logger.Info("lite instance subscription synced, lite pool ready for acquire")
				continue
			}
			insSpec, ok := event.EventMsg.(*commonTypes.InstanceSpecification)
			if !ok {
				logger.Warnf("lite instance event type assertion failed, skip")
				continue
			}
			funcKey := insSpec.CreateOptions[types.FunctionKeyNote]
			if funcKey == "" {
				logger.Warnf("lite instance event missing funcKey in CreateOptions, skip")
				continue
			}
			if !ls.isFuncEnabled(funcKey) {
				continue
			}
			pool := ls.getPool(funcKey)
			if pool == nil {
				logger.Warnf("lite instance event: pool %s not found (funcSpec event not yet synced), skip", funcKey)
				continue
			}
			// Snapshot pool.funcSpec under poolsMu.RLock to avoid a data race with
			// upsertPool: the writer holds both poolsMu.Lock and pool.Lock when
			// swapping the pointer, so this RLock is excluded from the swap.
			// Readers that already hold pool.Lock (e.g. sessionBindingKey call
			// sites in operation.go/expiry.go) are excluded by pool.Lock too.
			// BuildInstanceFromInsSpec may be long-running and must not hold the
			// lock; reading the snapshotted pointer is safe because upsertPool
			// only swaps the pointer, never mutates the old *FunctionSpecification.
			ls.poolsMu.RLock()
			funcSpec := pool.funcSpec
			ls.poolsMu.RUnlock()
			instance := utils.BuildInstanceFromInsSpec(insSpec, funcSpec)
			switch event.EventType {
			case registry.SubEventTypeUpdate:
				ls.handleInstanceUpdate(pool, instance)
			case registry.SubEventTypeDelete:
				ls.handleInstanceDelete(pool, instance)
			}
		}
	}
}

func (ls *LiteScheduler) processSchedulerEvents() {
	logger := log.GetLogger()
	for {
		select {
		case <-ls.stopCh:
			logger.Info("lite scheduler-proxy event loop exiting")
			return
		case event, ok := <-ls.schedulerCh:
			if !ok {
				logger.Warn("lite scheduler-proxy channel closed, event loop exiting")
				return
			}
			logger.Debugf("lite scheduler observed ring change: type %v", event.EventType)
			for _, pool := range ls.Pools() {
				pool.Lock()
				for _, instance := range pool.instances {
					if instance.SessionCtxID == "" {
						continue
					}
					routingKey := sessionContextRoutingKey(pool.funcKey, instance.SessionCtxID)
					if ls.ownerProxy != nil {
						if _, owned := ls.ownerProxy.CheckHashOwner(routingKey); owned {
							continue
						}
					}
					instance.IdleSince = time.Time{}
					instance.Reclaiming = false
				}
				pool.Unlock()
			}
		}
	}
}

func (ls *LiteScheduler) upsertPool(funcSpec *types.FunctionSpecification) {
	logger := log.GetLogger().With(zap.String("funcKey", funcSpec.FuncKey))
	ls.poolsMu.Lock()
	defer ls.poolsMu.Unlock()
	pool, ok := ls.pools[funcSpec.FuncKey]
	if !ok {
		pool = &LiteFunctionPool{
			funcKey: funcSpec.FuncKey, funcSpec: funcSpec,
			instances: map[string]*LiteInstance{}, sessions: map[string]*sessionBinding{},
			dispatcher:   newDispatcher(funcSpec),
			sessionStore: newLiteSessionStore(funcSpec.FuncKey),
		}
		ls.pools[funcSpec.FuncKey] = pool
		logger.Infof("lite pool created: dispatcher %s", pool.dispatcher.Policy())
		return
	}
	// Swap pool.funcSpec under pool.Lock so readers holding pool.Lock/RLock
	// (sessionBindingKey call sites in operation.go/expiry.go) and the
	// poolsMu.RLock snapshot in processInstanceEvents are all excluded from
	// the swap. Lock order poolsMu.Lock -> pool.Lock matches deletePool, no
	// inversion.
	pool.Lock()
	pool.funcSpec = funcSpec
	pool.Unlock()
	logger.Debug("lite pool funcSpec updated")
}

func (ls *LiteScheduler) deletePool(funcKey string) {
	logger := log.GetLogger().With(zap.String("funcKey", funcKey))
	ls.poolsMu.Lock()
	pool, ok := ls.pools[funcKey]
	if ok {
		delete(ls.pools, funcKey)
	}
	ls.poolsMu.Unlock()
	if !ok {
		return
	}
	pool.Lock()
	sessionIDs := make([]string, 0, len(pool.sessions))
	for sid, binding := range pool.sessions {
		binding.stopTimer()
		sessionIDs = append(sessionIDs, sid)
	}
	pool.sessions = make(map[string]*sessionBinding)
	pool.Unlock()
	// Stop the async worker first so no in-flight op races the sync cleanup,
	// then synchronously delete all external records.
	pool.sessionStore.stop()
	pool.sessionStore.cleanExternalRecords(sessionIDs)
	ls.allocMu.Lock()
	for id, alloc := range ls.allocations {
		if alloc.FuncKey == funcKey {
			delete(ls.allocations, id)
			ls.removeExpiryTask(id)
		}
	}
	ls.allocMu.Unlock()
	logger.Info("lite pool deleted and its allocations purged")
}

func (ls *LiteScheduler) handleInstanceUpdate(pool *LiteFunctionPool, ins *types.Instance) {
	logger := log.GetLogger().With(zap.String("funcKey", pool.funcKey), zap.String("instanceID", ins.InstanceID))
	pool.Lock()
	defer pool.Unlock()
	switch mapStatus(ins.InstanceStatus.Code) {
	case InstanceStatusRunning, InstanceStatusSubHealth:
		next := buildLiteInstanceFromInstance(ins)
		if current := pool.instances[ins.InstanceID]; current != nil {
			next.InUse = current.InUse
			next.IdleSince = current.IdleSince
			next.Reclaiming = current.Reclaiming
		}
		pool.instances[ins.InstanceID] = next
		logger.Debugf("lite instance upserted: status %d, capacity %d", ins.InstanceStatus.Code, ins.ConcurrentNum)
	case InstanceStatusUnavailable:
		ls.removeInstanceLocked(pool, ins.InstanceID)
		logger.Infof("lite instance marked unavailable, removed: %s", ins.InstanceID)
	}
}

func (ls *LiteScheduler) handleInstanceDelete(pool *LiteFunctionPool, ins *types.Instance) {
	logger := log.GetLogger().With(zap.String("funcKey", pool.funcKey), zap.String("instanceID", ins.InstanceID))
	pool.Lock()
	defer pool.Unlock()
	ls.removeInstanceLocked(pool, ins.InstanceID)
	logger.Infof("lite instance deleted from pool")
}

func (ls *LiteScheduler) removeInstanceLocked(pool *LiteFunctionPool, instanceID string) {
	delete(pool.instances, instanceID)
	for sid, binding := range pool.sessions {
		if binding.instanceID == instanceID {
			pool.removeSessionBinding(sid)
		}
	}
	ls.allocMu.Lock()
	for allocID, alloc := range ls.allocations {
		if alloc.InstanceID == instanceID && alloc.FuncKey == pool.funcKey {
			delete(ls.allocations, allocID)
			ls.removeExpiryTask(allocID)
		}
	}
	ls.allocMu.Unlock()
}
