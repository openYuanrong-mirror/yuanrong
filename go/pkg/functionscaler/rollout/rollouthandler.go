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

// Package rollout -
package rollout

import (
	"encoding/json"
	"errors"
	"strconv"
	"strings"
	"sync"

	"yuanrong.org/kernel/pkg/common/faas_common/logger/log"
)

var (
	globalRolloutConfig = &Config{}
)

// GetGlobalRolloutConfig -
func GetGlobalRolloutConfig() *Config {
	return globalRolloutConfig
}

// GrayRatio -
type GrayRatio struct {
	BlueRatio string `json:"blue-ratio"`
}

// Config rollout radio config -
type Config struct {
	IsGaryUpdating bool
	CurrentRatio   int
	sync.RWMutex
}

const (
	maxRatio = 100
)

// GetCurrentRatio -
func (rc *Config) GetCurrentRatio() int {
	rc.RLock()
	ratio := rc.CurrentRatio
	rc.RUnlock()
	return ratio
}

// IsUpdating -
func (rc *Config) IsUpdating() bool {
	rc.RLock()
	isUpdating := rc.IsGaryUpdating
	rc.RUnlock()
	return isUpdating
}

// SetUpdating -
func (rc *Config) SetUpdating(isUpdating bool) {
	rc.Lock()
	rc.IsGaryUpdating = isUpdating
	rc.Unlock()
}

// ProcessRatioUpdate -
func (rc *Config) ProcessRatioUpdate(ratioData []byte) error {
	rc.Lock()
	defer rc.Unlock()
	rolloutRatio := &GrayRatio{}
	err := json.Unmarshal(ratioData, rolloutRatio)
	if err != nil {
		log.GetLogger().Errorf("failed to process ratio update, unmarshal error %s", err.Error())
		return err
	}
	ratio, err := strconv.Atoi(strings.TrimSuffix(rolloutRatio.BlueRatio, "%"))
	if err != nil {
		log.GetLogger().Errorf("failed to process ratio update, ratio parse error %s", err.Error())
		return err
	}
	if ratio > maxRatio {
		log.GetLogger().Errorf("failed to process ratio update, ratio %d is invalid", ratio)
		return errors.New("blue ratio larger than 100%")
	}
	rc.CurrentRatio = ratio
	if ratio != 0 && ratio != maxRatio {
		rc.IsGaryUpdating = true
	} else {
		rc.IsGaryUpdating = false
	}
	log.GetLogger().Infof("succeed to update rollout ratio to %d%", ratio)
	return nil
}

// ProcessRatioDelete -
func (rc *Config) ProcessRatioDelete() {
	rc.Lock()
	defer rc.Unlock()
	rc.IsGaryUpdating = false
	rc.CurrentRatio = 0
}
