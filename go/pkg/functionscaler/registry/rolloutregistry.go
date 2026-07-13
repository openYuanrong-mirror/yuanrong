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
	"strings"
	"sync"

	"yuanrong.org/kernel/pkg/common/faas_common/constant"
	"yuanrong.org/kernel/pkg/common/faas_common/etcd3"
	"yuanrong.org/kernel/pkg/common/faas_common/logger/log"
	"yuanrong.org/kernel/pkg/functionscaler/config"
	"yuanrong.org/kernel/pkg/functionscaler/rollout"
)

const (
	rolloutConfigKeyLen = 5
	clusterIndex        = 4
)

// RolloutRegistry watches Rollout event of etcd
type RolloutRegistry struct {
	subscriberChans []chan SubEvent
	configWatcher   etcd3.Watcher
	configDone      chan struct{}
	stopCh          <-chan struct{}
	sync.RWMutex
}

var (
	rolloutEtcdWatcherStartListFunc = func(watcher etcd3.Watcher) {
		watcher.StartList()
	}
	rolloutEtcdWatcherStartWatchFunc = func(watcher etcd3.Watcher) {
		watcher.StartWatch()
	}
)

// NewRolloutRegistry will create RolloutRegistry
func NewRolloutRegistry(stopCh <-chan struct{}) *RolloutRegistry {
	rolloutRegistry := &RolloutRegistry{
		configDone: make(chan struct{}, 1),
		stopCh:     stopCh,
	}
	return rolloutRegistry
}

func (rr *RolloutRegistry) initWatcher(etcdClient *etcd3.EtcdClient) {
	if !config.GlobalConfig.EnableRollout {
		return
	}
	rr.configWatcher = etcd3.NewEtcdWatcher(
		constant.RolloutConfigPrefix,
		rr.watcherFilterForConfig,
		rr.watcherHandlerForConfig,
		rr.stopCh,
		etcdClient)
	rolloutEtcdWatcherStartListFunc(rr.configWatcher)
}

// WaitForETCDList -
func (rr *RolloutRegistry) WaitForETCDList() {
	select {
	case <-rr.configDone:
		log.GetLogger().Infof("receive rollout config list done, stop waiting ETCD list")
		return
	case <-rr.stopCh:
		log.GetLogger().Warnf("registry is stopped, stop waiting ETCD list")
		return
	}
}

// RunWatcher will start etcd watch process for instance event
func (rr *RolloutRegistry) RunWatcher() {
	if !config.GlobalConfig.EnableRollout {
		return
	}
	go rolloutEtcdWatcherStartWatchFunc(rr.configWatcher)
}

// watcherFilterForConfig will filter alias event from etcd event eg:/sn/faas-scheduler/gray/cluster001
func (rr *RolloutRegistry) watcherFilterForConfig(event *etcd3.Event) bool {
	items := strings.Split(event.Key, keySeparator)
	if len(items) != rolloutConfigKeyLen {
		return true
	}
	if items[clusterIndex] != config.GlobalConfig.ClusterID {
		return true
	}
	return false
}

// watcherHandlerForConfig will handle instance event from etcd
func (rr *RolloutRegistry) watcherHandlerForConfig(event *etcd3.Event) {
	log.GetLogger().Infof("handling rollout ratio config event type %d key %s", event.Type, event.Key)
	switch event.Type {
	case etcd3.SYNCED:
		log.GetLogger().Infof("received rollout ratio config synced event")
		rr.configDone <- struct{}{}
	case etcd3.PUT:
		err := rollout.GetGlobalRolloutConfig().ProcessRatioUpdate(event.Value)
		if err != nil {
			log.GetLogger().Errorf("process ratio update error: %s", err.Error())
			return
		}
		rr.publishEvent(SubEventTypeUpdate, rollout.GetGlobalRolloutConfig().GetCurrentRatio())
	case etcd3.DELETE:
		rollout.GetGlobalRolloutConfig().ProcessRatioDelete()
		rr.publishEvent(SubEventTypeUpdate, rollout.GetGlobalRolloutConfig().GetCurrentRatio())
	case etcd3.ERROR:
		log.GetLogger().Warnf("etcd error event: %s", event.Value)
	default:
		log.GetLogger().Warnf("unsupported event, key: %s", event.Key)
	}
}

// addSubscriberChan will add channel, subscribed by FaaSScheduler
func (rr *RolloutRegistry) addSubscriberChan(subChan chan SubEvent) {
	rr.Lock()
	rr.subscriberChans = append(rr.subscriberChans, subChan)
	rr.Unlock()
}

// publishEvent will publish instance event via channel
func (rr *RolloutRegistry) publishEvent(eventType EventType, ratio int) {
	for _, subChan := range rr.subscriberChans {
		if subChan != nil {
			subChan <- SubEvent{
				EventType: eventType,
				EventMsg:  ratio,
			}
		}
	}
}
