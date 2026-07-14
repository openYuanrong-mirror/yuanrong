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


// Package metrics -
package metrics

import (
	"context"
	"net/http"
	"sync"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	k8stype "k8s.io/apimachinery/pkg/types"

	"yuanrong.org/kernel/pkg/common/faas_common/logger/log"
	"yuanrong.org/kernel/pkg/common/faas_common/tls"
	"yuanrong.org/kernel/pkg/common/faas_common/wisecloudtool"
	"yuanrong.org/kernel/pkg/functionscaler/config"
	"yuanrong.org/kernel/pkg/functionscaler/types"
)

var (
	pendingRequest   = map[*types.InstanceAcquireRequest]*k8stype.NamespacedName{}
	pendingRequestMu sync.RWMutex

	metricsReporter = wisecloudtool.NewMetricProvider()
)

// InitServerMetric start prometheus http server
func InitServerMetric(stopCh <-chan struct{}) {
	if config.GlobalConfig.Scenario != types.ScenarioWiseCloud {
		return
	}
	// start metric server
	serveMetric(stopCh, config.GlobalConfig.MetricsAddr)
}

func serveMetric(stopCh <-chan struct{}, metricAddr string) {
	mux := http.NewServeMux()
	mux.Handle("/metrics", promhttp.Handler())
	// 启动 HTTP 服务器
	server := &http.Server{Addr: metricAddr, Handler: mux}
	go func() {
		if err := startServer(server); err != nil && err != http.ErrServerClosed {
			log.GetLogger().Errorf("Metrics HTTP server failed: %v", err)
		}
	}()

	// 等待停止信号
	<-stopCh
	log.GetLogger().Infof("Shutting down Metrics server...")
	if err := server.Shutdown(context.Background()); err != nil {
		log.GetLogger().Errorf("Server shutdown failed: %v", err)
	} else {
		log.GetLogger().Infof("Server exited cleanly")
	}
}

func startServer(httpServer *http.Server) error {
	if !config.GlobalConfig.MetricsHTTPSEnable || config.GlobalConfig.HTTPSConfig == nil {
		err := httpServer.ListenAndServe()
		if err != nil {
			log.GetLogger().Errorf("failed to http ListenAndServe: %s", err.Error())
		}
		return err
	}
	err := tls.InitTLSConfig(*config.GlobalConfig.HTTPSConfig)
	if err != nil {
		log.GetLogger().Errorf("failed to init the HTTPS config: %s", err.Error())
		return err
	}
	httpServer.TLSConfig = tls.GetClientTLSConfig()
	err = httpServer.ListenAndServeTLS("", "")
	if err != nil {
		log.GetLogger().Errorf("failed to HTTPListenAndServeTLS: %s", err.Error())
		return err
	}
	return nil
}

// EnsureConcurrencyGaugeWithLabel clear yuanrong_concurrency_num
func EnsureConcurrencyGaugeWithLabel(funcKey string, invokeLabel string, labels []string) {
	if config.GlobalConfig.Scenario != types.ScenarioWiseCloud {
		return
	}
	if len(labels) != 8 { // 祥云调用label标准长度
		log.GetLogger().Warnf("create yuanrong_concurrency_num gauge with label failed, labels len is %d", len(labels))
		return
	}

	metricsReporter.AddWorkLoad(funcKey, invokeLabel, &k8stype.NamespacedName{
		Namespace: labels[5], // namespace index
		Name:      labels[6], // name index
	})
	if err := metricsReporter.EnsureConcurrencyGaugeWithLabel(labels); err != nil {
		log.GetLogger().Warnf("create yuanrong_concurrency_num gauge with label failed, err is %s", err.Error())
	}
}

// EnsureLeaseRequestTotal clear yuanrong_lease_total
func EnsureLeaseRequestTotal(labels []string) {
	if config.GlobalConfig.Scenario != types.ScenarioWiseCloud {
		return
	}
	if err := metricsReporter.EnsureLeaseRequestTotalWithLabel(labels); err != nil {
		log.GetLogger().Warnf("create yuanrong_lease_total counter with label failed, err is %s", err.Error())
	}
}

// OnAcquireLease inc metric when lease acquired
func OnAcquireLease(insAcqReq *types.InstanceAllocation) {
	if config.GlobalConfig.Scenario != types.ScenarioWiseCloud {
		return
	}
	if insAcqReq == nil || insAcqReq.Instance == nil {
		log.GetLogger().Warnf("inc metric for lease with label failed, instance info is empty")
		return
	}
	if err := metricsReporter.IncConcurrencyGaugeWithLabel(insAcqReq.Instance.MetricLabelValues); err != nil {
		log.GetLogger().Warnf("inc lease gauge with label failed, err is %s", err.Error())
	}
	if err := metricsReporter.IncLeaseRequestTotalWithLabel(insAcqReq.Instance.MetricLabelValues); err != nil {
		log.GetLogger().Warnf("inc concurrency gauge with label failed, err is %s", err.Error())
	}
}

// OnReleaseLease dec metric when lease released
func OnReleaseLease(insAcqReq *types.InstanceAllocation) {
	if config.GlobalConfig.Scenario != types.ScenarioWiseCloud {
		return
	}
	if insAcqReq == nil || insAcqReq.Instance == nil {
		log.GetLogger().Warnf("dec metric for lease with label failed, instance info is empty")
		return
	}
	if err := metricsReporter.DecConcurrencyGaugeWithLabel(insAcqReq.Instance.MetricLabelValues); err != nil {
		log.GetLogger().Warnf("dec concurrency gauge with label failed, err is %s", err.Error())
	}
}

func OnPendingRequestAdd(insAcqReq *types.InstanceAcquireRequest) {
	if config.GlobalConfig.Scenario != types.ScenarioWiseCloud {
		return
	}
	if insAcqReq == nil || insAcqReq.FuncSpec == nil || insAcqReq.ResSpec == nil {
		log.GetLogger().Errorf("insAcqReq invalid, skip")
		return
	}

	deployment := metricsReporter.GetRandomDeployment(insAcqReq.FuncSpec.FuncKey, insAcqReq.ResSpec.InvokeLabel)
	if deployment == nil {
		log.GetLogger().Infof("cold starting, no need inc metrics for %s", insAcqReq.FuncSpec.FuncKey)
		return
	}

	pendingRequestMu.Lock()
	pendingRequest[insAcqReq] = deployment
	pendingRequestMu.Unlock()
	invokeLabel := insAcqReq.ResSpec.InvokeLabel

	err := metricsReporter.IncConcurrencyGaugeWithLabel(wisecloudtool.GetMetricLabels(&insAcqReq.FuncSpec.FuncMetaData,
		invokeLabel, deployment.Namespace, deployment.Name, "pendingRequest"))
	if err != nil {
		log.GetLogger().Warnf("inc concurrency gauge with label failed, err is %s", err.Error())
	}
}

func OnPendingRequestRelease(insAcqReq *types.InstanceAcquireRequest) {
	if config.GlobalConfig.Scenario != types.ScenarioWiseCloud {
		return
	}
	if insAcqReq == nil || insAcqReq.FuncSpec == nil || insAcqReq.ResSpec == nil {
		log.GetLogger().Errorf("insAcqReq invalid, skip")
		return
	}
	pendingRequestMu.Lock()
	deployment, ok := pendingRequest[insAcqReq]
	delete(pendingRequest, insAcqReq)
	pendingRequestMu.Unlock()
	if !ok {
		log.GetLogger().Warnf("pending request not store, %s, %s",
			insAcqReq.FuncSpec.FuncKey, insAcqReq.ResSpec.InvokeLabel)
		return
	}

	if !metricsReporter.Exist(insAcqReq.FuncSpec.FuncKey, insAcqReq.ResSpec.InvokeLabel) {
		log.GetLogger().Infof("function instance config has been clean, skip, %s, %s",
			insAcqReq.FuncSpec.FuncKey, insAcqReq.ResSpec.InvokeLabel)
		return
	}
	invokeLabel := insAcqReq.ResSpec.InvokeLabel
	labels := wisecloudtool.GetMetricLabels(&insAcqReq.FuncSpec.FuncMetaData, invokeLabel, deployment.Namespace,
		deployment.Name, "pendingRequest")
	if err := metricsReporter.DecConcurrencyGaugeWithLabel(labels); err != nil {
		log.GetLogger().Warnf("dec concurrency gauge with label failed, err is %s", err.Error())
	}
}

// ClearConcurrencyGaugeWithLabel clear yuanrong_concurrency_num
func ClearConcurrencyGaugeWithLabel(labels []string) {
	if config.GlobalConfig.Scenario != types.ScenarioWiseCloud {
		return
	}
	metricsReporter.ClearConcurrencyGaugeWithLabel(labels)
}

// ClearLeaseRequestTotal clear yuanrong_lease_total
func ClearLeaseRequestTotal(labels []string) {
	if config.GlobalConfig.Scenario != types.ScenarioWiseCloud {
		return
	}
	metricsReporter.ClearLeaseRequestTotalWithLabel(labels)
}

// ClearMetricsForFunction Clear deployments for function version.
func ClearMetricsForFunction(funcSpec *types.FunctionSpecification) {
	if config.GlobalConfig.Scenario != types.ScenarioWiseCloud {
		return
	}
	metricsReporter.ClearMetricsForFunction(&funcSpec.FuncMetaData)
}

// ClearMetricsForFunctionInsConfig Clear deployments for function version label
func ClearMetricsForFunctionInsConfig(funcSpec *types.FunctionSpecification, invokeLabel string) {
	if config.GlobalConfig.Scenario != types.ScenarioWiseCloud {
		return
	}
	metricsReporter.ClearMetricsForInsConfig(&funcSpec.FuncMetaData, invokeLabel)
}
