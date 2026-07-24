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

// Package registry -
package registry

import (
	"fmt"
	"os"
	"strings"
	"sync"

	"yuanrong.org/kernel/pkg/common/faas_common/constant"
	"yuanrong.org/kernel/pkg/common/faas_common/etcd3"
	"yuanrong.org/kernel/pkg/common/faas_common/instance"
	"yuanrong.org/kernel/pkg/common/faas_common/logger/log"
	"yuanrong.org/kernel/pkg/common/faas_common/types"
	"yuanrong.org/kernel/pkg/common/faas_common/urnutils"
	"yuanrong.org/kernel/pkg/common/faas_common/utils"
	"yuanrong.org/kernel/pkg/functionscaler/config"
	"yuanrong.org/kernel/pkg/functionscaler/rollout"
	"yuanrong.org/kernel/pkg/functionscaler/selfregister"
)

var (
	tokenType = os.Getenv(constant.FaaSSchedulerTokenTypeEnvKey)
)

// FaasSchedulerRegistry watches faasscheduler instance event of etcd
type FaasSchedulerRegistry struct {
	subscriberChans             []chan SubEvent
	functionScheduler           map[string]*types.InstanceSpecification
	moduleScheduler             *ModuleSchedulerInfos
	instanceMap                 map[string]*types.InstanceSpecification
	schedulerHashWatcher        etcd3.Watcher
	schedulerBlueHashWatcher    etcd3.Watcher
	schedulerInstanceWatcher    etcd3.Watcher
	discoveryKeyType            string
	schedulerInstanceListDoneCh chan struct{}
	schedulerHashListDoneCh     chan struct{}
	stopCh                      <-chan struct{}
	sync.RWMutex
}

// ModuleSchedulerInfos -
type ModuleSchedulerInfos struct {
	schedulerInsSpecInfos map[string]*types.InstanceSpecification
	schedulerInsInfos     map[string]*types.InstanceInfo
	leaseIds              map[string]map[string]bool
}

// AllSchedulerInfo scheduler info
type AllSchedulerInfo struct {
	SchedulerFuncKey           string                `json:"schedulerFuncKey"`
	SchedulerIDList            []string              `json:"schedulerIDList"`
	SchedulerInstanceList      []*types.InstanceInfo `json:"schedulerInstanceList"`
	BlueSchedulerInstanceList  []*types.InstanceInfo `json:"blueSchedulerInstanceList"`
	GreenSchedulerInstanceList []*types.InstanceInfo `json:"greenSchedulerInstanceList"`
	BlueRatio                  int                   `json:"blueRatio"`
}

// NewFaasSchedulerRegistry will create FaasSchedulerRegistry
func NewFaasSchedulerRegistry(stopCh <-chan struct{}) *FaasSchedulerRegistry {
	discoveryKeyType := constant.SchedulerKeyTypeFunction
	if config.GlobalConfig.SchedulerDiscovery != nil {
		discoveryKeyType = config.GlobalConfig.SchedulerDiscovery.KeyPrefixType
	}
	faasSchedulerRegistry := &FaasSchedulerRegistry{
		functionScheduler: make(map[string]*types.InstanceSpecification, constant.DefaultMapSize),
		moduleScheduler: &ModuleSchedulerInfos{
			schedulerInsSpecInfos: make(map[string]*types.InstanceSpecification, constant.DefaultMapSize),
			schedulerInsInfos:     make(map[string]*types.InstanceInfo, constant.DefaultMapSize),
			leaseIds:              make(map[string]map[string]bool, constant.DefaultMapSize),
		},
		instanceMap:                 make(map[string]*types.InstanceSpecification, constant.DefaultMapSize),
		discoveryKeyType:            discoveryKeyType,
		schedulerInstanceListDoneCh: make(chan struct{}, 1),
		schedulerHashListDoneCh:     make(chan struct{}, 1),
		stopCh:                      stopCh,
	}
	return faasSchedulerRegistry
}

func (fsr *FaasSchedulerRegistry) initWatcher(etcdClient *etcd3.EtcdClient) {
	fsr.initSchedulerHashWatcher(etcdClient)
	fsr.initSchedulerInstanceWatcher(etcdClient)
	fsr.WaitForETCDList()
}

func (fsr *FaasSchedulerRegistry) initSchedulerHashWatcher(etcdClient *etcd3.EtcdClient) {
	fsr.schedulerHashWatcher = etcd3.NewEtcdWatcher(
		constant.SchedulerHashPrefix,
		fsr.schedulerHashFilter,
		fsr.schedulerHashHandler,
		fsr.stopCh,
		etcdClient)
	fsr.schedulerHashWatcher.StartList()

	fsr.schedulerBlueHashWatcher = etcd3.NewEtcdWatcher(
		constant.SchedulerBlueHashPrefix,
		fsr.schedulerBlueHashFilter,
		fsr.schedulerHashHandler,
		fsr.stopCh,
		etcdClient)
	fsr.schedulerBlueHashWatcher.StartList()
}

func (fsr *FaasSchedulerRegistry) initSchedulerInstanceWatcher(etcdClient *etcd3.EtcdClient) {
	fsr.schedulerInstanceWatcher = etcd3.NewEtcdWatcher(
		instanceEtcdPrefix,
		fsr.schedulerInstanceFilter,
		fsr.schedulerInstanceHandler,
		fsr.stopCh,
		etcdClient)
	fsr.schedulerInstanceWatcher.StartList()
}

// WaitForETCDList -
func (fsr *FaasSchedulerRegistry) WaitForETCDList() {
	log.GetLogger().Infof("start to wait faasscheduler ETCD list")
	instanceListDone := false
	hashListDone := false
	for !instanceListDone || !hashListDone {
		select {
		case <-fsr.schedulerHashListDoneCh:
			log.GetLogger().Infof("receive scheduler hash list done")
			hashListDone = true
		case <-fsr.schedulerInstanceListDoneCh:
			log.GetLogger().Infof("receive scheduler instance list done")
			instanceListDone = true
		case <-fsr.stopCh:
			log.GetLogger().Warnf("registry is stopped, stop waiting ETCD list")
			return
		}
	}
}

// RunWatcher -
func (fsr *FaasSchedulerRegistry) RunWatcher() {
	go fsr.schedulerHashWatcher.StartWatch()
	go fsr.schedulerBlueHashWatcher.StartWatch()
	go fsr.schedulerInstanceWatcher.StartWatch()
}

func (fsr *FaasSchedulerRegistry) schedulerInstanceFilter(event *etcd3.Event) bool {
	return !isFaaSScheduler(event.Key)
}

func (fsr *FaasSchedulerRegistry) schedulerHashFilter(event *etcd3.Event) bool {
	return !strings.Contains(event.Key, constant.SchedulerHashPrefix)
}

func (fsr *FaasSchedulerRegistry) schedulerBlueHashFilter(event *etcd3.Event) bool {
	return !strings.Contains(event.Key, constant.SchedulerBlueHashPrefix)
}

func (fsr *FaasSchedulerRegistry) schedulerHashHandler(event *etcd3.Event) {
	log.GetLogger().Infof("scheduler hash event type %d received: %+v", event.Type, event.Key)
	if event.Type == etcd3.SYNCED {
		log.GetLogger().Infof("received faasscheduler hash synced event")
		fsr.schedulerHashListDoneCh <- struct{}{}
		return
	}

	if fsr.discoveryKeyType == constant.SchedulerKeyTypeModule {
		fsr.handleModuleSchedulerHashEvent(event)
	} else {
		fsr.handleFunctionSchedulerHashEvent(event)
	}
}

func (fsr *FaasSchedulerRegistry) schedulerInstanceHandler(event *etcd3.Event) {
	log.GetLogger().Infof("scheduler instance event type %d key: %s", event.Type, event.Key)
	if event.Type == etcd3.SYNCED {
		log.GetLogger().Infof("received faasscheduler instance synced event")
		fsr.schedulerInstanceListDoneCh <- struct{}{}
		return
	}
	switch event.Type {
	case etcd3.PUT:
		fsr.handleSchedulerInstanceUpdate(event)
	case etcd3.DELETE:
		fsr.handleSchedulerInstanceRemove(event)
	default:
		log.GetLogger().Warnf("unsupported event type %d for key %s", event.Type, event.Key)
	}
}

func (fsr *FaasSchedulerRegistry) handleModuleSchedulerHashEvent(event *etcd3.Event) {
	switch event.Type {
	case etcd3.PUT:
		fsr.handleModuleSchedulerUpdate(event)
	case etcd3.DELETE:
		fsr.handleModuleSchedulerRemove(event)
	default:
		log.GetLogger().Warnf("unsupported event type %d for key %s", event.Type, event.Key)
	}
}

func (fsr *FaasSchedulerRegistry) handleFunctionSchedulerHashEvent(event *etcd3.Event) {
	switch event.Type {
	case etcd3.PUT:
		fsr.handleFunctionSchedulerUpdate(event)
	case etcd3.DELETE:
		fsr.handleFunctionSchedulerRemove(event)
	default:
		log.GetLogger().Warnf("unsupported event type %d for key %s", event.Type, event.Key)
	}
}

func (fsr *FaasSchedulerRegistry) addLeaseBare(eventKey string, adaptedInstanceName string) {
	_, isLeaseKey := utils.GetInstanceNameFromSchedulerLeaseEtcdKey(eventKey)
	if !isLeaseKey {
		return
	}
	lease := utils.ParseLeaseFromSchedulerLeaseEtcdKey(eventKey)
	leaseIds, ok := fsr.moduleScheduler.leaseIds[adaptedInstanceName]
	if !ok {
		leaseIds = make(map[string]bool)
		fsr.moduleScheduler.leaseIds[adaptedInstanceName] = leaseIds
	}
	leaseIds[lease] = true
}

func (fsr *FaasSchedulerRegistry) delLeaseBare(eventKey string, adaptedInstanceName string) {
	_, isLeaseKey := utils.GetInstanceNameFromSchedulerLeaseEtcdKey(eventKey)
	if !isLeaseKey {
		return
	}
	lease := utils.ParseLeaseFromSchedulerLeaseEtcdKey(eventKey)
	leaseIds, ok := fsr.moduleScheduler.leaseIds[adaptedInstanceName]
	if !ok {
		return
	}
	delete(leaseIds, lease)
	if len(leaseIds) == 0 {
		delete(fsr.moduleScheduler.leaseIds, adaptedInstanceName)
	}
}

// when registerMode is set to registerByContend, the etcd value of module scheduler may be empty if no scheduler locks
// this key
func (fsr *FaasSchedulerRegistry) handleModuleSchedulerUpdate(event *etcd3.Event) {
	instanceName := ""
	var adaptedInstanceName string
	isLeaseKey := false
	eventTokenType, versionFlag := getTokenTypeAndVersionFlag(event.Key)
	if instanceName, isLeaseKey = utils.GetInstanceNameFromSchedulerLeaseEtcdKey(event.Key); isLeaseKey {
		fsr.Lock()
		adaptedInstanceName = fmt.Sprintf("%s-%s", eventTokenType, instanceName)
		fsr.addLeaseBare(event.Key, adaptedInstanceName)
		fsr.Unlock()
	} else {
		insSpec := instance.GetInsSpecFromEtcdValue(event.Key, event.Value)
		if insSpec == nil || insSpec.InstanceID == "" {
			log.GetLogger().Infof("ignore invalid instance spec from key %s", event.Key)
			return
		}
		insInfo, err := utils.GetSchedulerInfoFromEtcdKey(event.Key)
		if err != nil {
			log.GetLogger().Errorf("failed to parse instanceInfo from key %s error %s", event.Key, err.Error())
			return
		}
		instanceName = insInfo.InstanceName
		insInfo.InstanceID = insSpec.InstanceID
		insInfo.Address = selfregister.NormalizeSchedulerAddress(insSpec.RuntimeAddress)
		adaptedInstanceName = fmt.Sprintf("%s-%s", eventTokenType, instanceName)
		fsr.Lock()
		fsr.moduleScheduler.schedulerInsInfos[adaptedInstanceName] = insInfo
		fsr.moduleScheduler.schedulerInsSpecInfos[adaptedInstanceName] = insSpec
		fsr.Unlock()
	}
	fsr.RLock()
	_, ok1 := fsr.moduleScheduler.leaseIds[adaptedInstanceName]
	insInfo, ok2 := fsr.moduleScheduler.schedulerInsInfos[adaptedInstanceName]
	insSpec := fsr.moduleScheduler.schedulerInsSpecInfos[adaptedInstanceName]
	fsr.RUnlock()
	if !ok1 || !ok2 {
		return
	}

	exclusivity := ""
	if insSpec != nil {
		if insSpec.CreateOptions != nil {
			exclusivity = insSpec.CreateOptions[constant.SchedulerExclusivityKey]
		}
	}
	selfregister.GlobalSchedulerProxy.Add(insInfo, exclusivity, eventTokenType, versionFlag)
	fsr.publishEvent(SubEventTypeUpdate, insSpec)
}

func getTokenTypeAndVersionFlag(key string) (string, bool) {
	var eventTokenType string
	if strings.Contains(key, constant.SchedulerBlueHashPrefix) {
		eventTokenType = constant.BlueTokenType
	} else if strings.Contains(key, constant.SchedulerHashPrefix) {
		eventTokenType = constant.GreenTokenType
	}
	if tokenType == "" && strings.EqualFold(eventTokenType, constant.GreenTokenType) {
		return eventTokenType, true
	}
	return eventTokenType, strings.EqualFold(eventTokenType, tokenType)
}

// when registerMode is set to registerByContend, the etcd value of module scheduler may be empty if no scheduler locks
// this key
func (fsr *FaasSchedulerRegistry) handleFunctionSchedulerUpdate(event *etcd3.Event) {
	insSpec := instance.GetInsSpecFromEtcdValue(event.Key, event.Value)
	insInfo, err := utils.GetFunctionSchedulerInfoFromEtcdKey(event.Key)
	if err != nil {
		log.GetLogger().Errorf("failed to parse instanceInfo from key %s error %s", event.Key, err.Error())
		return
	}

	exclusivity := ""
	if insSpec != nil {
		insInfo.InstanceID = insSpec.InstanceID
		insInfo.Address = selfregister.NormalizeSchedulerAddress(insSpec.RuntimeAddress)
		if insSpec.CreateOptions != nil {
			exclusivity = insSpec.CreateOptions[constant.SchedulerExclusivityKey]
		}
	}
	selfregister.GlobalSchedulerProxy.Add(insInfo, exclusivity, "", true)

	fsr.Lock()
	fsr.functionScheduler[insInfo.InstanceName] = insSpec
	fsr.Unlock()
	fsr.publishEvent(SubEventTypeUpdate, insSpec)
}

func (fsr *FaasSchedulerRegistry) handleFunctionSchedulerRemove(event *etcd3.Event) {
	insSpec := instance.GetInsSpecFromEtcdValue(event.Key, event.Value)
	insInfo, err := utils.GetFunctionSchedulerInfoFromEtcdKey(event.Key)
	if err != nil {
		log.GetLogger().Errorf("failed to parse instanceInfo from key %s error %s", event.Key, err.Error())
		return
	}
	if fsr.discoveryKeyType == constant.SchedulerKeyTypeFunction {
		selfregister.GlobalSchedulerProxy.Remove(insInfo.InstanceName, "", true)
	}
	fsr.Lock()
	delete(fsr.functionScheduler, insInfo.InstanceName)
	fsr.Unlock()
	fsr.publishEvent(SubEventTypeRemove, insSpec)
}

func (fsr *FaasSchedulerRegistry) handleModuleSchedulerRemove(event *etcd3.Event) {
	instanceName := ""
	isLeaseKey := false
	eventTokenType, versionFlag := getTokenTypeAndVersionFlag(event.Key)
	var adaptedInstanceName string
	instanceName, isLeaseKey = utils.GetInstanceNameFromSchedulerLeaseEtcdKey(event.Key)
	if !isLeaseKey {
		insInfo, err := utils.GetSchedulerInfoFromEtcdKey(event.Key)
		if err != nil {
			log.GetLogger().Errorf("failed to parse instanceInfo from key %s error %s", event.Key, err.Error())
			return
		}
		instanceName = insInfo.InstanceName
	}
	adaptedInstanceName = fmt.Sprintf("%s-%s", eventTokenType, instanceName)
	defer func() {
		fsr.Lock()
		if isLeaseKey {
			fsr.delLeaseBare(event.Key, adaptedInstanceName)
		} else {
			delete(fsr.moduleScheduler.schedulerInsInfos, adaptedInstanceName)
			delete(fsr.moduleScheduler.schedulerInsSpecInfos, adaptedInstanceName)
		}
		fsr.Unlock()
	}()

	fsr.RLock()
	length := len(fsr.moduleScheduler.leaseIds[adaptedInstanceName])
	insInfo, ok := fsr.moduleScheduler.schedulerInsInfos[adaptedInstanceName]
	insSpec := fsr.moduleScheduler.schedulerInsSpecInfos[adaptedInstanceName]
	fsr.RUnlock()
	if length != 1 || !ok {
		return
	}

	selfregister.GlobalSchedulerProxy.Remove(insInfo.InstanceName, eventTokenType, versionFlag)
	fsr.publishEvent(SubEventTypeRemove, insSpec)
}

func (fsr *FaasSchedulerRegistry) handleSchedulerInstanceUpdate(event *etcd3.Event) {
	insSpec := instance.GetInsSpecFromEtcdValue(event.Key, event.Value)
	insInfo, err := utils.GetFunctionInstanceInfoFromEtcdKey(event.Key)
	if err != nil {
		log.GetLogger().Errorf("failed to parse instanceInfo from key %s error %s", event.Key, err.Error())
		return
	}

	fsr.Lock()
	fsr.instanceMap[insInfo.InstanceID] = insSpec
	fsr.Unlock()
	if insSpec.InstanceID == selfregister.SelfInstanceID {
		selfregister.SetSelfInstanceSpec(insSpec)
	}
}

func (fsr *FaasSchedulerRegistry) handleSchedulerInstanceRemove(event *etcd3.Event) {
	insInfo, err := utils.GetFunctionInstanceInfoFromEtcdKey(event.Key)
	if err != nil {
		log.GetLogger().Errorf("failed to parse instanceInfo from key %s error %s", event.Key, err.Error())
		return
	}

	fsr.Lock()
	delete(fsr.instanceMap, insInfo.InstanceID)
	fsr.Unlock()
}

// isFaaSScheduler used to filter the etcd event which stands for a faas scheduler
func isFaaSScheduler(etcdPath string) bool {
	info, err := utils.GetFunctionInstanceInfoFromEtcdKey(etcdPath)
	if err != nil {
		return false
	}
	return strings.Contains(info.FunctionName, "faasscheduler")
}

// GetAllSchedulerInfo return scheduler info
func (fsr *FaasSchedulerRegistry) GetAllSchedulerInfo() *AllSchedulerInfo {
	schedulerInfo := &AllSchedulerInfo{}
	selfregister.GlobalSchedulerProxy.GreenFaaSSchedulers.Range(func(key, value any) bool {
		faaSScheduler, ok := value.(*types.InstanceInfo)
		if !ok {
			return true
		}
		schedulerInfo.SchedulerFuncKey = urnutils.CombineFunctionKey(faaSScheduler.TenantID,
			faaSScheduler.FunctionName, faaSScheduler.Version)
		schedulerInfo.GreenSchedulerInstanceList = append(schedulerInfo.GreenSchedulerInstanceList, faaSScheduler)
		return true
	})
	selfregister.GlobalSchedulerProxy.BlueFaaSSchedulers.Range(func(key, value any) bool {
		faaSScheduler, ok := value.(*types.InstanceInfo)
		if !ok {
			return true
		}
		schedulerInfo.SchedulerFuncKey = urnutils.CombineFunctionKey(faaSScheduler.TenantID,
			faaSScheduler.FunctionName, faaSScheduler.Version)
		schedulerInfo.BlueSchedulerInstanceList = append(schedulerInfo.BlueSchedulerInstanceList, faaSScheduler)
		return true
	})
	if len(schedulerInfo.GreenSchedulerInstanceList) == 0 && len(schedulerInfo.BlueSchedulerInstanceList) == 0 {
		selfregister.GlobalSchedulerProxy.FaaSSchedulers.Range(func(key, value any) bool {
			faasSchedulerID, ok := key.(string)
			if !ok {
				return true
			}
			faaSScheduler, ok := value.(*types.InstanceInfo)
			if !ok {
				return true
			}
			schedulerInfo.SchedulerIDList = append(schedulerInfo.SchedulerIDList, faasSchedulerID)
			schedulerInfo.SchedulerFuncKey = urnutils.CombineFunctionKey(faaSScheduler.TenantID,
				faaSScheduler.FunctionName, faaSScheduler.Version)
			schedulerInfo.SchedulerInstanceList = append(schedulerInfo.SchedulerInstanceList, faaSScheduler)
			return true
		})
	}
	schedulerInfo.BlueRatio = rollout.GetGlobalRolloutConfig().GetCurrentRatio()
	return schedulerInfo
}

// addSubscriberChan will add channel, subscribed by FaaSScheduler
func (fsr *FaasSchedulerRegistry) addSubscriberChan(subChan chan SubEvent) {
	fsr.Lock()
	fsr.subscriberChans = append(fsr.subscriberChans, subChan)
	fsr.Unlock()
}

// publishEvent will publish instance event via channel
func (fsr *FaasSchedulerRegistry) publishEvent(eventType EventType, insSpec *types.InstanceSpecification) {
	for _, subChan := range fsr.subscriberChans {
		if subChan != nil {
			subChan <- SubEvent{
				EventType: eventType,
				EventMsg:  insSpec,
			}
		}
	}
}
