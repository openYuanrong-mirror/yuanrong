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

// Package config is common logger client
package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"reflect"
	"testing"

	"github.com/smartystreets/goconvey/convey"
)

func withEnv(key, value string) func() {
	oldValue, existed := os.LookupEnv(key)
	_ = os.Setenv(key, value)
	return func() {
		if existed {
			_ = os.Setenv(key, oldValue)
			return
		}
		_ = os.Unsetenv(key)
	}
}

func TestInitConfig(t *testing.T) {
	convey.Convey("TestInitConfig", t, func() {
		convey.Convey("test 1", func() {
			oldExtractCoreInfoFromEnv := extractCoreInfoFromEnv
			oldValidateFilePath := validateFilePath
			oldMkdirAll := mkdirAll
			extractCoreInfoFromEnv = func(env string) (CoreInfo, error) {
				return defaultCoreInfo, nil
			}
			validateFilePath = func(path string) error {
				return nil
			}
			mkdirAll = func(path string, perm os.FileMode) error {
				return nil
			}
			defer func() {
				extractCoreInfoFromEnv = oldExtractCoreInfoFromEnv
				validateFilePath = oldValidateFilePath
				mkdirAll = oldMkdirAll
			}()
			coreInfo, err := GetCoreInfoFromEnv()
			fmt.Printf("log config:%+v\n", coreInfo)
			convey.So(err, convey.ShouldEqual, nil)
		})
	})
}

func TestInitConfigWithReadFileError(t *testing.T) {
	convey.Convey("TestInitConfigWithEmptyPath", t, func() {
		convey.Convey("test 1", func() {
			defer withEnv(logConfigKey, "")()
			coreInfo, err := GetCoreInfoFromEnv()
			fmt.Printf("error:%s\n", err)
			fmt.Printf("log config:%+v\n", coreInfo)
			convey.So(err, convey.ShouldNotEqual, nil)
		})
	})
}

func TestInitConfigWithErrorJson(t *testing.T) {
	convey.Convey("TestInitConfigWithEmptyPath", t, func() {
		convey.Convey("test 1", func() {
			mockErrorJson := "{\n\"filepath\": \"/home/sn/mock\",\n\"level\": \"INFO\",\n\"maxsize\": " +
				"500,\n\"maxbackups\": 1,\n\"maxage\": 1,\n\"compress\": true\n"
			defer withEnv(logConfigKey, mockErrorJson)()
			coreInfo, err := GetCoreInfoFromEnv()
			fmt.Printf("error:%s\n", err)
			fmt.Printf("log config:%+v\n", coreInfo)
			convey.So(err, convey.ShouldNotEqual, nil)
		})
	})
}

func TestInitConfigWithEmptyPath(t *testing.T) {
	convey.Convey("TestInitConfigWithEmptyPath", t, func() {
		convey.Convey("test 1", func() {
			mockCfgInfo := "{\n\"filepath\": \"\",\n\"level\": \"INFO\",\n\"maxsize\": " +
				"500,\n\"maxbackups\": 1,\n\"maxage\": 1,\n\"compress\": true\n}"
			defer withEnv(logConfigKey, mockCfgInfo)()
			coreInfo, err := GetCoreInfoFromEnv()
			fmt.Printf("error:%s\n", err)
			fmt.Printf("log config:%+v\n", coreInfo)
			convey.So(err, convey.ShouldNotEqual, nil)
		})
	})
}

func TestInitConfigWithValidateError(t *testing.T) {
	convey.Convey("TestInitConfigWithEmptyPath", t, func() {
		convey.Convey("test 1", func() {
			mockErrorJson := "{\n\"filepath\": \"some_relative_path\",\n\"level\": \"INFO\",\n\"maxsize\": " +
				"500,\n\"maxbackups\": 1,\n\"maxage\": 1}"
			defer withEnv(logConfigKey, mockErrorJson)()
			coreInfo, err := GetCoreInfoFromEnv()
			fmt.Printf("error:%s\n", err)
			fmt.Printf("log config:%+v\n", coreInfo)
			convey.So(err, convey.ShouldNotEqual, nil)
		})
	})
}

func TestGetDefaultCoreInfo(t *testing.T) {
	tests := []struct {
		name string
		want CoreInfo
	}{
		{
			name: "test001",
			want: CoreInfo{
				FilePath:   "/home/snuser/log",
				Level:      "INFO",
				Tick:       0, // Unit: Second
				First:      0, // Unit: Number of logs
				Thereafter: 0, // Unit: Number of logs
				SingleSize: 100,
				Threshold:  10,
				Tracing:    false, // tracing log switch
				Disable:    false, // Disable file logger
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := GetDefaultCoreInfo(); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("GetDefaultCoreInfo() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestExtractCoreInfoFromEnv(t *testing.T) {
	normalInfo, _ := json.Marshal(defaultCoreInfo)
	abnormalInfo1 := "{"
	abnormal2 := CoreInfo{
		FilePath:   "",
		Level:      "INFO",
		Tick:       10,    // Unit: Second
		First:      10,    // Unit: Number of logs
		Thereafter: 5,     // Unit: Number of logs
		Tracing:    false, // tracing log switch
		Disable:    false, // Disable file logger
	}
	abnormalInfo2, _ := json.Marshal(abnormal2)
	type args struct {
		env string
	}
	tests := []struct {
		name     string
		args     args
		want     CoreInfo
		wantErr  bool
		envValue string
	}{
		{
			name:     "case1",
			args:     args{logConfigKey},
			want:     defaultCoreInfo,
			wantErr:  false,
			envValue: string(normalInfo),
		},
		{
			name:     "case2",
			args:     args{logConfigKey},
			want:     defaultCoreInfo,
			wantErr:  true,
			envValue: abnormalInfo1,
		},
		{
			name:     "case3",
			args:     args{logConfigKey},
			want:     defaultCoreInfo,
			wantErr:  true,
			envValue: string(abnormalInfo2),
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			defer withEnv(tt.args.env, tt.envValue)()
			got, err := ExtractCoreInfoFromEnv(tt.args.env)
			if (err != nil) != tt.wantErr {
				t.Errorf("ExtractCoreInfoFromEnv() error = %v, wantErr %v", err, tt.wantErr)
				return
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ExtractCoreInfoFromEnv() got = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestGetCoreInfoFromEnv(t *testing.T) {
	convey.Convey("GetCoreInfoFromEnv", t, func() {
		convey.Convey("ValidateFilePath error", func() {
			oldExtractCoreInfoFromEnv := extractCoreInfoFromEnv
			extractCoreInfoFromEnv = func(env string) (CoreInfo, error) {
				return CoreInfo{FilePath: "../test"}, nil
			}
			defer func() {
				extractCoreInfoFromEnv = oldExtractCoreInfoFromEnv
			}()
			_, err := GetCoreInfoFromEnv()
			convey.So(err, convey.ShouldBeError)
		})

		convey.Convey("MkdirAll error", func() {
			oldExtractCoreInfoFromEnv := extractCoreInfoFromEnv
			oldValidateFilePath := validateFilePath
			oldMkdirAll := mkdirAll
			extractCoreInfoFromEnv = func(env string) (CoreInfo, error) {
				return CoreInfo{FilePath: "/home/test"}, nil
			}
			validateFilePath = func(path string) error {
				return nil
			}
			mkdirAll = func(path string, perm os.FileMode) error {
				return errors.New("create dir error")
			}
			defer func() {
				extractCoreInfoFromEnv = oldExtractCoreInfoFromEnv
				validateFilePath = oldValidateFilePath
				mkdirAll = oldMkdirAll
			}()
			_, err := GetCoreInfoFromEnv()
			convey.So(err, convey.ShouldBeError)
		})

		convey.Convey("success", func() {
			oldExtractCoreInfoFromEnv := extractCoreInfoFromEnv
			oldValidateFilePath := validateFilePath
			oldMkdirAll := mkdirAll
			extractCoreInfoFromEnv = func(env string) (CoreInfo, error) {
				return CoreInfo{FilePath: "/home/test"}, nil
			}
			validateFilePath = func(path string) error {
				return nil
			}
			mkdirAll = func(path string, perm os.FileMode) error {
				return nil
			}
			defer func() {
				extractCoreInfoFromEnv = oldExtractCoreInfoFromEnv
				validateFilePath = oldValidateFilePath
				mkdirAll = oldMkdirAll
			}()
			env, err := GetCoreInfoFromEnv()
			convey.So(err, convey.ShouldBeNil)
			convey.So(env.FilePath, convey.ShouldEqual, "/home/test")
		})
	})
}
