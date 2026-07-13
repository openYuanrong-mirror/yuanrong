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

package concurrencyscheduler

import (
	"testing"

	"github.com/stretchr/testify/assert"

	"yuanrong.org/kernel/pkg/functionscaler/utils"
)

func Test_sessionRecord_GetOrReplaceDesignateThreadFromAvailThdMap(t *testing.T) {
	record := &sessionRecord{
		availThdMap: make(map[string]struct{}, utils.DefaultMapSize),
		allocThdMap: make(map[string]struct{}, utils.DefaultMapSize),
	}
	record.PutThreadToAllocThdMap("aaa")
	record.PutThreadToAllocThdMap("bbb")
	record.MarkThreadAsAvailable("aaa")
	record.MarkThreadAsAvailable("bbb")
	thdId, err := record.GetOrReplaceDesignateThreadFromAvailThdMap("")
	assert.Nil(t, err)
	assert.Equal(t, len(record.availThdMap), 1)
	record.MarkThreadAsAvailable(thdId)
	acqThd, err := record.GetOrReplaceDesignateThreadFromAvailThdMap(thdId)
	assert.Nil(t, err)
	assert.Equal(t, acqThd, thdId)
	assert.Equal(t, len(record.availThdMap), 1)
	_, err = record.GetOrReplaceDesignateThreadFromAvailThdMap(thdId)
	assert.NotNil(t, err)
	record.MarkThreadAsAvailable(thdId)
	acqThd, err = record.GetOrReplaceDesignateThreadFromAvailThdMap("ccc")
	assert.Nil(t, err)
	assert.Equal(t, acqThd, "ccc")
}
