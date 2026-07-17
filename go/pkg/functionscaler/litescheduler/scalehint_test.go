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
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/smartystreets/goconvey/convey"
	"github.com/stretchr/testify/assert"

	"yuanrong.org/kernel/pkg/common/faas_common/loadbalance"
	"yuanrong.org/kernel/pkg/common/faas_common/logger/log"
	"yuanrong.org/kernel/pkg/common/faas_common/statuscode"
	commonTypes "yuanrong.org/kernel/pkg/common/faas_common/types"
	"yuanrong.org/kernel/pkg/functionscaler/selfregister"
)

func TestNoopSenderNilHintDoesNotPanic(t *testing.T) {
	s := NewNoopSender()
	assert.NotPanics(t, func() {
		s.Send(nil)
	})
}

func TestNoopSenderSendsWithoutPanic(t *testing.T) {
	s := NewNoopSender()
	assert.NotPanics(t, func() {
		s.Send(&ScaleHint{FuncKey: "unknown/f/v1", Reason: "cold_start"})
	})
}

func newTestProxyWithOwner(addr string) *selfregister.SchedulerProxy {
	proxy := selfregister.NewSchedulerProxy(loadbalance.NewCHGeneric())
	proxy.Add(&commonTypes.InstanceInfo{
		InstanceName: "owner-1", InstanceID: "owner-id-1", Address: addr,
	}, "", "", true)
	return proxy
}

func TestHTTPSenderAccepted(t *testing.T) {
	convey.Convey("owner accepts hint with 202", t, func() {
		var gotPath string
		var gotBody []byte
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			gotPath = r.URL.Path
			gotBody, _ = io.ReadAll(r.Body)
			w.WriteHeader(http.StatusAccepted)
		}))
		defer server.Close()
		s := NewHTTPSender(newTestProxyWithOwner(strings.TrimPrefix(server.URL, "http://")))
		s.Send(&ScaleHint{FuncKey: "t1/fA/v1", SessionID: "s1", Reason: "cold_start", TraceID: "tr"})
		convey.So(gotPath, convey.ShouldEqual, "/scalehint")
		var hint ScaleHint
		_ = json.Unmarshal(gotBody, &hint)
		convey.So(hint.FuncKey, convey.ShouldEqual, "t1/fA/v1")
		convey.So(hint.SessionID, convey.ShouldEqual, "s1")
	})
}

func TestHTTPSenderDedup(t *testing.T) {
	convey.Convey("second hint within window is deduped", t, func() {
		var count int32
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			atomic.AddInt32(&count, 1)
			w.WriteHeader(http.StatusAccepted)
		}))
		defer server.Close()
		s := NewHTTPSender(newTestProxyWithOwner(strings.TrimPrefix(server.URL, "http://")))
		s.Send(&ScaleHint{FuncKey: "t1/fA/v1", TraceID: "tr1"})
		s.Send(&ScaleHint{FuncKey: "t1/fA/v1", TraceID: "tr2"})
		convey.So(atomic.LoadInt32(&count), convey.ShouldEqual, 1)
	})
}

func TestHTTPSenderRingNotReady(t *testing.T) {
	convey.Convey("empty ring drops hint without panic", t, func() {
		proxy := selfregister.NewSchedulerProxy(loadbalance.NewCHGeneric())
		s := NewHTTPSender(proxy)
		convey.So(func() { s.Send(&ScaleHint{FuncKey: "t1/fA/v1"}) }, convey.ShouldNotPanic)
	})
}

func TestHTTPSenderFailureReleasesDedup(t *testing.T) {
	convey.Convey("a failed dispatch can be retried immediately", t, func() {
		var count int32
		proxy := selfregister.NewSchedulerProxy(loadbalance.NewCHGeneric())
		s := NewHTTPSender(proxy).(*httpSender)
		hint := &ScaleHint{FuncKey: "t1/fA/v1", TraceID: "tr1"}

		s.Send(hint)
		_, deduped := s.dedup.Get(hint.FuncKey)
		convey.So(deduped, convey.ShouldBeFalse)

		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			atomic.AddInt32(&count, 1)
			w.WriteHeader(http.StatusAccepted)
		}))
		defer server.Close()
		proxy.Add(&commonTypes.InstanceInfo{
			InstanceName: "owner-1", InstanceID: "owner-id-1",
			Address: strings.TrimPrefix(server.URL, "http://"),
		}, "", "", true)

		s.Send(hint)
		convey.So(atomic.LoadInt32(&count), convey.ShouldEqual, 1)
		_, deduped = s.dedup.Get(hint.FuncKey)
		convey.So(deduped, convey.ShouldBeTrue)
	})
}

func TestHTTPSenderHTTPFailureReleasesDedup(t *testing.T) {
	convey.Convey("a rejected HTTP dispatch can be retried immediately", t, func() {
		var count int32
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if atomic.AddInt32(&count, 1) == 1 {
				w.WriteHeader(http.StatusInternalServerError)
				return
			}
			w.WriteHeader(http.StatusAccepted)
		}))
		defer server.Close()
		s := NewHTTPSender(newTestProxyWithOwner(strings.TrimPrefix(server.URL, "http://"))).(*httpSender)
		hint := &ScaleHint{FuncKey: "t1/fA/v1", TraceID: "tr1"}

		s.Send(hint)
		_, deduped := s.dedup.Get(hint.FuncKey)
		convey.So(deduped, convey.ShouldBeFalse)

		s.Send(hint)
		convey.So(atomic.LoadInt32(&count), convey.ShouldEqual, 2)
		_, deduped = s.dedup.Get(hint.FuncKey)
		convey.So(deduped, convey.ShouldBeTrue)
	})
}

func TestHTTPSenderConcurrentDedup(t *testing.T) {
	convey.Convey("concurrent hints share one in-flight dispatch", t, func() {
		var count int32
		entered := make(chan struct{})
		release := make(chan struct{})
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if atomic.AddInt32(&count, 1) == 1 {
				close(entered)
			}
			<-release
			w.WriteHeader(http.StatusAccepted)
		}))
		defer server.Close()
		s := NewHTTPSender(newTestProxyWithOwner(strings.TrimPrefix(server.URL, "http://")))

		const concurrentSends = 32
		start := make(chan struct{})
		var ready sync.WaitGroup
		var done sync.WaitGroup
		ready.Add(concurrentSends)
		done.Add(concurrentSends)
		for i := 0; i < concurrentSends; i++ {
			go func() {
				defer done.Done()
				ready.Done()
				<-start
				s.Send(&ScaleHint{FuncKey: "t1/fA/v1", TraceID: "tr"})
			}()
		}
		ready.Wait()
		close(start)
		<-entered
		close(release)
		done.Wait()

		convey.So(atomic.LoadInt32(&count), convey.ShouldEqual, 1)
	})
}

func TestHTTPSenderRerouteOnNonOwner(t *testing.T) {
	convey.Convey("150464 response reroutes to new owner", t, func() {
		var secondHit int32
		second := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			atomic.AddInt32(&secondHit, 1)
			w.WriteHeader(http.StatusAccepted)
		}))
		defer second.Close()
		first := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			body, _ := json.Marshal(ScaleHintResponse{
				ErrorCode:    statuscode.AcquireNonOwnerSchedulerErrorCode,
				ErrorMessage: "owner-id-2",
			})
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write(body)
		}))
		defer first.Close()
		proxy := selfregister.NewSchedulerProxy(loadbalance.NewCHGeneric())
		proxy.Add(&commonTypes.InstanceInfo{InstanceName: "owner-1", InstanceID: "owner-id-1",
			Address: strings.TrimPrefix(first.URL, "http://")}, "", "", true)
		proxy.Add(&commonTypes.InstanceInfo{InstanceName: "owner-2", InstanceID: "owner-id-2",
			Address: strings.TrimPrefix(second.URL, "http://")}, "", "", true)
		s := NewHTTPSender(proxy).(*httpSender)
		body, _ := json.Marshal(&ScaleHint{FuncKey: "t1/fA/v1"})
		s.sendWithRetry(proxy.FindByInstanceID("owner-id-1"), "tr", body, log.GetLogger())
		convey.So(atomic.LoadInt32(&secondHit), convey.ShouldEqual, 1)
	})
}
