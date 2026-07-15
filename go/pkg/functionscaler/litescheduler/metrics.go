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
	"github.com/prometheus/client_golang/prometheus"
	"yuanrong.org/kernel/pkg/functionscaler/selfregister"
)

const (
	liteMetricConcurrency = "faas_lite_concurrency_current"
	liteMetricCapacity    = "faas_lite_capacity_current"
	liteMetricSession     = "faas_lite_session_current"
	liteMetricInstance    = "faas_lite_instance_current"
	liteMetricAcquire     = "faas_lite_acquire_total"
	liteMetricRelease     = "faas_lite_release_total"
	liteMetricRetain      = "faas_lite_retain_total"
	liteMetricScaleHint   = "faas_lite_scale_hint_total"
)

func liteBaseLabels() []string {
	return []string{"scheduler_id", "tenant_id", "func_key", "policy"}
}

// LiteCollector implements prometheus.Collector; Gauges are read at scrape time.
type LiteCollector struct {
	scheduler        *LiteScheduler
	concurrencyDesc  *prometheus.Desc
	capacityDesc     *prometheus.Desc
	sessionDesc      *prometheus.Desc
	instanceDesc     *prometheus.Desc
	acquireCounter   *prometheus.CounterVec
	releaseCounter   *prometheus.CounterVec
	retainCounter    *prometheus.CounterVec
	scaleHintCounter *prometheus.CounterVec
}

// NewLiteCollector builds the collector. It does NOT register with the prometheus
// default registry; registration is a separate concern (callers register when ready,
// e.g. an InitMetric step). Avoiding global registration prevents duplicate-register
// panics when multiple LiteSchedulers are constructed (notably in tests).
func NewLiteCollector(scheduler *LiteScheduler) *LiteCollector {
	base := liteBaseLabels()
	resultLabels := append(append([]string{}, base...), "result")
	reasonLabels := append(append([]string{}, base...), "reason")
	return &LiteCollector{
		scheduler:        scheduler,
		concurrencyDesc:  prometheus.NewDesc(liteMetricConcurrency, "current local in-use concurrency", base, nil),
		capacityDesc:     prometheus.NewDesc(liteMetricCapacity, "current local concurrency capacity", base, nil),
		sessionDesc:      prometheus.NewDesc(liteMetricSession, "current local session binding count", base, nil),
		instanceDesc:     prometheus.NewDesc(liteMetricInstance, "current local schedulable instance count", base, nil),
		acquireCounter:   prometheus.NewCounterVec(prometheus.CounterOpts{Name: liteMetricAcquire, Help: "acquire result count"}, resultLabels),
		releaseCounter:   prometheus.NewCounterVec(prometheus.CounterOpts{Name: liteMetricRelease, Help: "release result count"}, resultLabels),
		retainCounter:    prometheus.NewCounterVec(prometheus.CounterOpts{Name: liteMetricRetain, Help: "retain result count"}, resultLabels),
		scaleHintCounter: prometheus.NewCounterVec(prometheus.CounterOpts{Name: liteMetricScaleHint, Help: "scale hint count"}, reasonLabels),
	}
}

func (c *LiteCollector) Describe(ch chan<- *prometheus.Desc) {
	ch <- c.concurrencyDesc
	ch <- c.capacityDesc
	ch <- c.sessionDesc
	ch <- c.instanceDesc
	c.acquireCounter.Describe(ch)
	c.releaseCounter.Describe(ch)
	c.retainCounter.Describe(ch)
	c.scaleHintCounter.Describe(ch)
}

func (c *LiteCollector) Collect(ch chan<- prometheus.Metric) {
	for funcKey, pool := range c.scheduler.Pools() {
		stats := pool.Stats()
		labels := []string{selfregister.SelfInstanceID, stats.TenantID, funcKey, stats.Policy}
		ch <- prometheus.MustNewConstMetric(c.concurrencyDesc, prometheus.GaugeValue, float64(stats.InUse), labels...)
		ch <- prometheus.MustNewConstMetric(c.capacityDesc, prometheus.GaugeValue, float64(stats.Capacity), labels...)
		ch <- prometheus.MustNewConstMetric(c.sessionDesc, prometheus.GaugeValue, float64(stats.SessionCount), labels...)
		ch <- prometheus.MustNewConstMetric(c.instanceDesc, prometheus.GaugeValue, float64(stats.InstanceCount), labels...)
	}
	c.acquireCounter.Collect(ch)
	c.releaseCounter.Collect(ch)
	c.retainCounter.Collect(ch)
	c.scaleHintCounter.Collect(ch)
}

// incAcquire/incRelease/incRetain/incScaleHint report request-path counters.
// Wired into operation.go: assignInstance (acquire success), handleRelease,
// handleRetain, and handleColdStart (scale hint). Each guards ls.metrics != nil
// since New may leave metrics nil in test harnesses.
func (c *LiteCollector) incAcquire(funcKey, tenantID, policy, result string) {
	c.acquireCounter.WithLabelValues(selfregister.SelfInstanceID, tenantID, funcKey, policy, result).Inc()
}
func (c *LiteCollector) incRelease(funcKey, tenantID, policy, result string) {
	c.releaseCounter.WithLabelValues(selfregister.SelfInstanceID, tenantID, funcKey, policy, result).Inc()
}
func (c *LiteCollector) incRetain(funcKey, tenantID, policy, result string) {
	c.retainCounter.WithLabelValues(selfregister.SelfInstanceID, tenantID, funcKey, policy, result).Inc()
}
func (c *LiteCollector) incScaleHint(funcKey, tenantID, reason string) {
	c.scaleHintCounter.WithLabelValues(selfregister.SelfInstanceID, tenantID, funcKey, "n/a", reason).Inc()
}
