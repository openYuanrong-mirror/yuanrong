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

// Package selfregister -
package selfregister

import (
	"encoding/json"
	"net"
	"os"
	"strings"
	"sync"
	"time"

	"go.uber.org/zap"
	"yuanrong.org/kernel/pkg/common/faas_common/constant"
	"yuanrong.org/kernel/pkg/common/faas_common/loadbalance"
	"yuanrong.org/kernel/pkg/common/faas_common/logger/log"
	"yuanrong.org/kernel/pkg/common/faas_common/types"
	"yuanrong.org/kernel/pkg/functionscaler/config"
)

const (
	// HashRingSize the concurrent hash ring length
	HashRingSize = 5000
	// GetHashLenInternal -
	GetHashLenInternal  = 10 * time.Millisecond
	etcdPathElementsLen = 14
)

var (
	// SelfInstanceID proxy is the singleton proxy
	SelfInstanceID string
	// SelfInstanceName is the instanceName used when discovery type is module
	SelfInstanceName string

	selfInstanceSpecLock sync.RWMutex
	selfInstanceSpec     *types.InstanceSpecification
)

var (
	// GlobalSchedulerProxy -
	GlobalSchedulerProxy = NewSchedulerProxy(
		loadbalance.LBFactory(loadbalance.SimpleHashGeneric))
)

// SchedulerProxy is used to get instances from FaaSScheduler via a grpc stream
type SchedulerProxy struct {
	// For version compatibility, FaaSSchedulers includes a complete list of schedulers
	// from the current(blue or green) ring system
	FaaSSchedulers      sync.Map
	GreenFaaSSchedulers sync.Map
	BlueFaaSSchedulers  sync.Map
	// used to select a FaaSScheduler by the func info Concurrent Consistent Hash
	loadBalance loadbalance.LoadBalance
}

func init() {
	log.GetLogger().Infof("set SelfInstanceID to %s", os.Getenv("INSTANCE_ID"))
	SelfInstanceID = os.Getenv("INSTANCE_ID")
}

// SetSelfInstanceName -
func SetSelfInstanceName(instanceName string) {
	log.GetLogger().Infof("set SelfInstanceName to %s", instanceName)
	SelfInstanceName = instanceName
}

// SetSelfInstanceSpec -
func SetSelfInstanceSpec(insSpec *types.InstanceSpecification) {
	var insSpecCopy *types.InstanceSpecification
	if insSpec != nil {
		bytes, err := json.Marshal(insSpec)
		if err != nil {
			return
		}
		err = json.Unmarshal(bytes, &insSpecCopy)
		if err != nil || insSpecCopy == nil {
			return
		}

		insSpecCopy.RuntimeAddress = NormalizeSchedulerAddress(insSpecCopy.RuntimeAddress)
	}
	selfInstanceSpecLock.Lock()
	selfInstanceSpec = insSpecCopy
	selfInstanceSpecLock.Unlock()
}

// NormalizeSchedulerAddress converts an instance runtime address to the
// scheduler HTTP endpoint used for internal dispatch (e.g. scaleHint). The
// runtime's port belongs to libruntime and must never be advertised as the
// scheduler HTTP port.
func NormalizeSchedulerAddress(runtimeAddr string) string {
	if runtimeAddr == "" {
		return ""
	}
	host, _, err := net.SplitHostPort(runtimeAddr)
	if err != nil {
		host = strings.Trim(runtimeAddr, "[]")
		if net.ParseIP(host) == nil {
			if index := strings.LastIndex(runtimeAddr, ":"); index > 0 {
				host = runtimeAddr[:index]
			} else {
				host = runtimeAddr
			}
		}
	}
	if host == "" {
		return ""
	}
	return net.JoinHostPort(host, GetFaaSSchedulerHttpPort())
}

func getSelfInstanceSpec() *types.InstanceSpecification {
	selfInstanceSpecLock.RLock()
	defer selfInstanceSpecLock.RUnlock()
	return selfInstanceSpec
}

// GetSchedulerProxyName -
func GetSchedulerProxyName() string {
	schedulerDiscovery := config.GlobalConfig.SchedulerDiscovery
	if schedulerDiscovery != nil && schedulerDiscovery.KeyPrefixType == constant.SchedulerKeyTypeModule {
		return SelfInstanceName
	}
	return SelfInstanceID
}

// NewSchedulerProxy return an instance pool which get the instance from the remote FaaSScheduler
func NewSchedulerProxy(lb loadbalance.LoadBalance) *SchedulerProxy {
	return &SchedulerProxy{
		loadBalance: lb,
	}
}

// Add an FaaSScheduler
func (sp *SchedulerProxy) Add(faaSScheduler *types.InstanceInfo, exclusivity string,
	tokenType string, currentVersionFlag bool) {
	if tokenType == constant.GreenTokenType {
		sp.GreenFaaSSchedulers.Store(faaSScheduler.InstanceName, faaSScheduler)
	} else if tokenType == constant.BlueTokenType {
		sp.BlueFaaSSchedulers.Store(faaSScheduler.InstanceName, faaSScheduler)
	}
	if !currentVersionFlag {
		log.GetLogger().Infof("no need to add scheduler %s to load balance for not currentVersion tokenType %s",
			faaSScheduler.InstanceName, tokenType)
		return
	}
	sp.FaaSSchedulers.Store(faaSScheduler.InstanceName, faaSScheduler)
	if exclusivity != "" {
		// do not add exclusivity scheduler to load balance
		log.GetLogger().Infof("no need to add scheduler %s to load balance for exclusivity %s",
			faaSScheduler.InstanceName, exclusivity)
		return
	}
	log.GetLogger().Debugf("add faasscheduler to proxy, id is %s, name is %s",
		faaSScheduler.InstanceID, faaSScheduler.InstanceName)
	sp.loadBalance.Add(faaSScheduler.InstanceName, 0)
}

// Remove a FaaSScheduler
func (sp *SchedulerProxy) Remove(instanceName string, tokenType string, versionFlag bool) {
	if versionFlag {
		sp.loadBalance.Remove(instanceName)
		sp.FaaSSchedulers.Delete(instanceName)
	}
	if tokenType == constant.GreenTokenType {
		sp.GreenFaaSSchedulers.Delete(instanceName)
	} else if tokenType == constant.BlueTokenType {
		sp.BlueFaaSSchedulers.Delete(instanceName)
	}
}

// Reset - reset hash anchor point
func (sp *SchedulerProxy) Reset() {
	sp.loadBalance.Reset()
}

// Contains - if hash ring contains this scheduelr
func (sp *SchedulerProxy) Contains(id string) bool {
	_, ok := sp.FaaSSchedulers.Load(id)
	return ok
}

// IsFuncOwner determine etcd event should or not to be deal with
func (sp *SchedulerProxy) IsFuncOwner(funcKey string) bool {
	_, ok := sp.CheckFuncOwner(funcKey)
	return ok
}

// selectHashOwner selects the FaaSScheduler owning hashKey via the load balance
// hash ring and returns its InstanceInfo, or nil when the ring is not ready or
// the selected entry is invalid. Shared by CheckHashOwner and FindHashOwner.
func (sp *SchedulerProxy) selectHashOwner(hashKey string) *types.InstanceInfo {
	logger := log.GetLogger().With(zap.Any("hashKey", hashKey))
	// select one FaaSScheduler by the hash key
	next := sp.loadBalance.Next(hashKey, false)
	faasSchedulerName, ok := next.(string)
	if !ok {
		logger.Errorf("failed to parse the result of load balance: %+v", next)
		return nil
	}
	if strings.TrimSpace(faasSchedulerName) == "" {
		logger.Errorf("no available faas scheduler was found")
		return nil
	}
	faaSSchedulerData, ok := sp.FaaSSchedulers.Load(faasSchedulerName)
	if !ok {
		logger.Errorf("failed to get the faas scheduler named %s", faasSchedulerName)
		return nil
	}
	faaSScheduler, ok := faaSSchedulerData.(*types.InstanceInfo)
	if !ok {
		logger.Errorf("invalid faas scheduler named %s: %#v", faasSchedulerName, faaSSchedulerData)
		return nil
	}
	return faaSScheduler
}

// CheckHashOwner determine if current scheduler is owner of the hashKey.
// Generic owner check by arbitrary hash key (funcKey for legacy, tenantID/sessionID for LiteScheduler).
func (sp *SchedulerProxy) CheckHashOwner(hashKey string) (string, bool) {
	logger := log.GetLogger().With(zap.Any("hashKey", hashKey))
	logger.Debugf("check which faas scheduler instance should process this hash key")
	faaSScheduler := sp.selectHashOwner(hashKey)
	if faaSScheduler == nil {
		return "", false
	}
	if faaSScheduler.InstanceName != GetSchedulerProxyName() {
		logger.Warnf("instanceID self is: %s, hash computed: %s", GetSchedulerProxyName(),
			faaSScheduler.InstanceName)
		return faaSScheduler.InstanceID, false
	}
	logger.Infof("this scheduler %s should process hash key", SelfInstanceID)
	return faaSScheduler.InstanceID, true
}

// CheckFuncOwner determine etcd event should or not to be deal with (legacy: funcKey dimension)
func (sp *SchedulerProxy) CheckFuncOwner(funcKey string) (string, bool) {
	return sp.CheckHashOwner(funcKey)
}

// WaitForHash wait for num of concurrent hash node to add
func (sp *SchedulerProxy) WaitForHash(num int) {
	if num == 0 {
		return
	}
	for {
		hashLen := 0
		sp.FaaSSchedulers.Range(func(k, v interface{}) bool {
			hashLen++
			return true
		})
		if hashLen < num {
			time.Sleep(GetHashLenInternal)
			continue
		}
		log.GetLogger().Infof("succeeded to create num: %d of hash ring node", num)
		return
	}
}

// FindHashOwner returns the full InstanceInfo of the scheduler owning hashKey,
// and whether the owner is this scheduler. Returns (nil, false) when the ring
// is not ready or the selected entry is invalid. It uses the extracted
// selectHashOwner for hash selection and exposes the address for HTTP dispatch.
func (sp *SchedulerProxy) FindHashOwner(hashKey string) (*types.InstanceInfo, bool) {
	faaSScheduler := sp.selectHashOwner(hashKey)
	if faaSScheduler == nil {
		return nil, false
	}
	owned := faaSScheduler.InstanceName == GetSchedulerProxyName()
	log.GetLogger().With(zap.Any("hashKey", hashKey)).Debugf(
		"hash owner is %s (instanceID %s, address %s, self %v)",
		faaSScheduler.InstanceName, faaSScheduler.InstanceID, faaSScheduler.Address, owned)
	return faaSScheduler, owned
}

// FindByInstanceID returns the InstanceInfo of the scheduler with the given
// InstanceID, or nil if not found. Used to resolve a redirected owner's address
// after a non-owner error code response. Only the current-version ring
// (FaaSSchedulers) is searched; Blue/Green maps are not included.
func (sp *SchedulerProxy) FindByInstanceID(instanceID string) *types.InstanceInfo {
	var found *types.InstanceInfo
	sp.FaaSSchedulers.Range(func(_, v interface{}) bool {
		info, ok := v.(*types.InstanceInfo)
		if ok && info.InstanceID == instanceID {
			found = info
			return false
		}
		return true
	})
	return found
}
