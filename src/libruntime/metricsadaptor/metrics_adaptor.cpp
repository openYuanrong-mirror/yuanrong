/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2024-2024. All rights reserved.
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

#include <dlfcn.h>
#include <cstdlib>
#include <sstream>
#include <string>
#include <unordered_set>
#include "metrics_context.h"
#include "metrics_adaptor.h"


#include "metrics/api/metric_data.h"
#include "metrics/api/null.h"
#include "metrics/api/provider.h"
#include "metrics/sdk/immediately_export_processor.h"
#include "metrics/sdk/meter_provider.h"
#include "src/dto/config.h"
#include "src/utility/logger/logger.h"
#include "src/utility/logger/fileutils.h"

namespace YR {
namespace Libruntime {
const char *const IMMEDIATELY_EXPORT = "immediatelyExport";
const char *const FILE_EXPORTER = "fileExporter";
const char *const PROMETHEUS_PUSH_EXPORTER = "prometheusPushExporter";
const char *const PROMETHEUS_PULL_EXPORTER = "prometheusPullExporter";
const char *const AOM_ALARM_EXPORTER = "aomAlarmExporter";
const char *const YR_SSL_PASSPHRASE_KEY = "YR_SSL_PASSPHRASE";
const char *const POD_NAME_ENV = "POD_NAME";
const char *const POD_NAMESPACE_ENV = "POD_NAMESPACE";
const char *const POD_LABEL = "pod";
const char *const NAMESPACE_LABEL = "namespace";
const std::unordered_set<std::string> SENSITIVE_CONFIG_KEYS = {
    "rootCertData", "certData", "keyData", "passphrase"
};

nlohmann::json RedactSensitiveMetricConfig(nlohmann::json config)
{
    if (!config.is_object()) {
        return config;
    }
    for (auto &[key, value] : config.items()) {
        if (SENSITIVE_CONFIG_KEYS.find(key) != SENSITIVE_CONFIG_KEYS.end()) {
            value = "***";
        } else if (value.is_object()) {
            value = RedactSensitiveMetricConfig(value);
        }
    }
    return config;
}

std::string GetSelfSoPath()
{
    Dl_info info;
    if (dladdr((void*)&GetSelfSoPath, &info) == 0) {
        return "";
    }
    std::string path(info.dli_fname);
    auto pos = path.find_last_of('/');
    if (pos == std::string::npos) {
        return "";
    }

    return path.substr(0, pos);
}

static std::string GetLibraryPath(const std::string &exporterType)
{
    auto path = GetSelfSoPath();
    std::string filePath = "";
    if (exporterType == FILE_EXPORTER) {
        filePath = path + "/libobservability-metrics-file-exporter.so";
    } else if (exporterType == PROMETHEUS_PUSH_EXPORTER) {
        filePath = path + "/libobservability-prometheus-push-exporter.so";
    } else if (exporterType == PROMETHEUS_PULL_EXPORTER) {
        filePath = path + "/libobservability-prometheus-pull-exporter.so";
    } else if (exporterType == AOM_ALARM_EXPORTER) {
        filePath = path + "/libobservability-aom-alarm-exporter.so";
    }
    YRLOG_INFO("exporter {} get library path: {}", exporterType, filePath);
    return filePath;
}

std::once_flag MetricsAdaptor::initFlag;
std::shared_ptr<MetricsAdaptor> MetricsAdaptor::instance = nullptr;

MetricsAdaptor::MetricsAdaptor() {}

bool MetricsAdaptor::IsInited() const
{
    return Initialized_;
}

void MetricsAdaptor::SetMetricsTLSConfig(const std::string &rootCertData, const std::string &certData,
                                         const std::string &keyData)
{
    metricsRootCertData_ = rootCertData;
    metricsCertData_ = certData;
    metricsKeyData_ = SensitiveData(keyData);
}

void MetricsAdaptor::Init(const nlohmann::json &json, bool userEnable)
{
    {
        std::lock_guard<std::mutex> lock(prometheus_pull_exporter_mutex_);
        if (prometheusPullExporter_ != nullptr) {
            prometheusPullExporter_->Shutdown();
            prometheusPullExporter_.reset();
        }
    }
    Initialized_ = false;
    userEnable_ = userEnable;
    metricSampleAllowAll_ = false;
    metricSampleEnabledInstruments_.clear();
    { std::lock_guard<std::mutex> l(instrument_kind_mutex_); instrumentKinds_.clear(); }
    { std::lock_guard<std::mutex> l(gauge_mutex_); doubleGaugeMap_.clear(); doubleGaugeSamples_.clear(); }
    { std::lock_guard<std::mutex> l(uint64_counter_mutex_); uInt64CounterMap_.clear(); uint64CounterSamples_.clear(); }
    { std::lock_guard<std::mutex> l(double_counter_mutex_); doubleCounterMap_.clear(); doubleCounterSamples_.clear(); }
    { std::lock_guard<std::mutex> l(alarm_mutex_); alarmMap_.clear(); }
    YRLOG_DEBUG("start to init metrics adaptor, userEnable {}", userEnable);
    if (json.find("backends") == json.end()) {
        YRLOG_WARN("metrics backends are none");
        return;
    }
    auto mp = std::make_shared<MetricsSdk::MeterProvider>(MetricsSdk::LiteBusParams{});
    auto backends = json.at("backends");
    auto getFileName = [this](std::string backendName) { return GetMetricsFilesName(backendName); };
    for (auto &[index, backend] : backends.items()) {
        YRLOG_DEBUG("metrics add backend index({})", index);
        for (auto &[key, value] : backend.items()) {
            if (key == IMMEDIATELY_EXPORT) {
                InitImmediatelyExport(mp, value, getFileName);
            } else {
                YRLOG_WARN("unknown backend key: {}", key);
            }
        }
    }
    MetricsApi::Provider::SetMeterProvider(mp);
}

void MetricsAdaptor::SetContextAttr(const std::string &attr, const std::string &value)
{
    metricsContext_.SetAttr(attr, value);
}

std::string MetricsAdaptor::GetContextValue(const std::string &attr) const
{
    return metricsContext_.GetAttr(attr);
}

void MetricsAdaptor::InitImmediatelyExport(const std::shared_ptr<MetricsSdk::MeterProvider> &mp,
                                           const nlohmann::json &backendValue,
                                           const std::function<std::string(std::string)> &getFileName)
{
    YRLOG_DEBUG("metrics add backend {}", IMMEDIATELY_EXPORT);
    if (backendValue.find("enable") == backendValue.end() || !backendValue.at("enable").get<bool>()) {
        YRLOG_DEBUG("metrics backend {} is not enabled", IMMEDIATELY_EXPORT);
        return;
    }
    std::string backendName;
    if (backendValue.find("name") != backendValue.end()) {
        backendName = backendValue.at("name");
        YRLOG_DEBUG("metrics add backend {} of {}", IMMEDIATELY_EXPORT, backendName);
        enabledBackends_.insert(backendName);
    }
    if (backendValue.find("custom") != backendValue.end()) {
        auto custom = backendValue.at("custom");
        if (custom.find("labels") != custom.end()) {
            auto labels = custom.at("labels");
            for (auto &label : labels.items()) {
                YRLOG_DEBUG("metrics backend {} of {} add custom label, key: {}, value: {}", IMMEDIATELY_EXPORT,
                            backendName, label.key(), label.value().dump());
                metricsContext_.SetAttr(label.key(), label.value());
            }
        }
    }
    if (backendValue.find("exporters") != backendValue.end()) {
        for (auto &[index, exporters] : backendValue.at("exporters").items()) {
            YRLOG_DEBUG("metrics add exporter index({}) for backend {}", index, backendName);
            SetImmediatelyExporters(mp, backendName, exporters, getFileName);
        }
    }
}

void MetricsAdaptor::SetImmediatelyExporters(const std::shared_ptr<observability::sdk::metrics::MeterProvider> &mp,
                                             const std::string &backendName, const nlohmann::json &exporters,
                                             const std::function<std::string(std::string)> &getFileName)
{
    if (mp == nullptr) {
        return;
    }
    for (auto &[key, value] : exporters.items()) {
        if (key == FILE_EXPORTER) {
            auto &&exporter = InitFileExporter(IMMEDIATELY_EXPORT, backendName, value, getFileName);
            if (exporter == nullptr) {
                continue;
            }
            Initialized_ = true;
            auto exportConfigs = BuildExportConfigs(value);
            AddMetricSampleEnabledInstruments(exportConfigs);
            exportConfigs.exporterName = key;
            exportConfigs.exportMode = MetricsSdk::ExportMode::IMMEDIATELY;
            auto processor = std::make_shared<observability::sdk::metrics::ImmediatelyExportProcessor>(
                std::move(exporter), exportConfigs);
            mp->AddMetricProcessor(std::move(processor));
        } else if (key == PROMETHEUS_PUSH_EXPORTER || key == PROMETHEUS_PULL_EXPORTER || key == AOM_ALARM_EXPORTER) {
            auto &&exporter = InitHttpExporter(key, IMMEDIATELY_EXPORT, backendName, value);
            if (exporter == nullptr) {
                YRLOG_ERROR("Failed to init exporter {}", key);
                continue;
            }
            Initialized_ = true;
            auto exportConfigs = BuildExportConfigs(value);
            AddMetricSampleEnabledInstruments(exportConfigs);
            if (key == PROMETHEUS_PULL_EXPORTER) {
                std::lock_guard<std::mutex> lock(prometheus_pull_exporter_mutex_);
                if (prometheusPullExporter_ != nullptr) {
                    prometheusPullExporter_->Shutdown();
                }
                prometheusPullExporter_ = exporter;
            }
            exportConfigs.exporterName = key;
            exportConfigs.exportMode = MetricsSdk::ExportMode::IMMEDIATELY;
            auto processor =
                std::make_shared<MetricsSdk::ImmediatelyExportProcessor>(std::move(exporter), exportConfigs);
            mp->AddMetricProcessor(std::move(processor));
        } else {
            YRLOG_WARN("unknown exporter name: {}", key);
        }
    }
}

std::shared_ptr<MetricsExporters::Exporter> MetricsAdaptor::InitHttpExporter(const std::string &httpExporterType,
                                                                             const std::string &backendKey,
                                                                             const std::string &backendName,
                                                                             const nlohmann::json &exporterValue)
{
    YRLOG_DEBUG("add exporter {} for backend {} of {}", httpExporterType, backendKey, backendName);
    if (exporterValue.find("enable") == exporterValue.end() || !exporterValue.at("enable").get<bool>()) {
        YRLOG_DEBUG("metrics exporter {} for backend {} of {} is not enabled", httpExporterType, backendKey,
                    backendName);
        return nullptr;
    }
    if (exporterValue.find("initConfig") == exporterValue.end()) {
        YRLOG_ERROR("parameter ip is invalid, exporter {} for backend {} of {}", httpExporterType, backendKey,
                    backendName);
        return nullptr;
    }
    auto initConfig = BuildHttpExporterInitConfig(httpExporterType, backendName, exporterValue);
    std::string error;
    return MetricsPlugin::LoadExporterFromLibrary(GetLibraryPath(httpExporterType), initConfig, error);
}

std::string MetricsAdaptor::BuildHttpExporterInitConfig(const std::string &httpExporterType,
                                                        const std::string &backendName,
                                                        const nlohmann::json &exporterValue)
{
    std::string initConfig;
    auto initConfigJson = exporterValue.at("initConfig");
    if (httpExporterType == PROMETHEUS_PUSH_EXPORTER || httpExporterType == AOM_ALARM_EXPORTER) {
        initConfigJson["jobName"] = "runtime";
        if (initConfigJson.find("ip") != initConfigJson.end() && initConfigJson.find("port") != initConfigJson.end()) {
            initConfigJson["endpoint"] =
                initConfigJson.at("ip").get<std::string>() + ":" + std::to_string(initConfigJson.at("port").get<int>());
        }
    }
    try {
        YRLOG_INFO("metrics http exporter for backend {}, initConfig: {}", backendName,
                   RedactSensitiveMetricConfig(initConfigJson).dump());
    } catch (std::exception &e) {
        YRLOG_ERROR("dump initConfigJson failed, error: {}", e.what());
    }
    if (httpExporterType == PROMETHEUS_PUSH_EXPORTER || httpExporterType == AOM_ALARM_EXPORTER) {
        ConfigurePushHttpExporterTLS(initConfigJson);
    }
    if (httpExporterType == PROMETHEUS_PULL_EXPORTER) {
        ConfigurePullHttpExporterTLS(initConfigJson);
    }
    try {
        initConfig = initConfigJson.dump();
    } catch (std::exception &e) {
        YRLOG_ERROR("dump initConfigJson failed, error: {}", e.what());
    }
    return initConfig;
}

void MetricsAdaptor::ConfigurePushHttpExporterTLS(nlohmann::json &initConfigJson)
{
    if (!Config::Instance().YR_SSL_ENABLE()) {
        return;
    }
    initConfigJson["isSSLEnable"] = true;
    initConfigJson["rootCertFile"] = Config::Instance().YR_SSL_ROOT_FILE();
    initConfigJson["certFile"] = Config::Instance().YR_SSL_CERT_FILE();
    initConfigJson["keyFile"] = Config::Instance().YR_SSL_KEY_FILE();
    auto ret = std::getenv(YR_SSL_PASSPHRASE_KEY);
    if (ret != nullptr) {
        initConfigJson["passphrase"] = ret;
        const int replaceOpt = 1;
        setenv(YR_SSL_PASSPHRASE_KEY, "", replaceOpt);
    } else {
        YRLOG_WARN("can not get metrics passphrase from env.");
    }
}

void MetricsAdaptor::ConfigurePullHttpExporterTLS(nlohmann::json &initConfigJson)
{
    if (!initConfigJson.value("isSSLEnable", false) || metricsRootCertData_.empty() || metricsCertData_.empty() ||
        metricsKeyData_.Empty()) {
        return;
    }
    initConfigJson["rootCertData"] = metricsRootCertData_;
    initConfigJson["certData"] = metricsCertData_;
    initConfigJson["keyData"] = std::string(metricsKeyData_.GetData(), metricsKeyData_.GetSize());
}

const MetricsSdk::ExportConfigs MetricsAdaptor::BuildExportConfigs(const nlohmann::json &exporterValue)
{
    try {
        YRLOG_DEBUG("Start to build export config {}", exporterValue.dump());
    } catch (std::exception &e) {
        YRLOG_ERROR("dump exporterValue failed, error: {}", e.what());
    }
    observability::sdk::metrics::ExportConfigs exportConfigs;
    if (exporterValue.contains("batchSize")) {
        exportConfigs.batchSize = exporterValue.at("batchSize");
    }
    if (exporterValue.contains("batchIntervalSec")) {
        exportConfigs.batchIntervalSec = exporterValue.at("batchIntervalSec");
    }
    if (exporterValue.contains("failureQueueMaxSize")) {
        exportConfigs.failureQueueMaxSize = exporterValue.at("failureQueueMaxSize");
    }
    if (exporterValue.contains("failureDataDir")) {
        exportConfigs.failureDataDir = exporterValue.at("failureDataDir");
    }
    if (exporterValue.contains("failureDataFileMaxCapacity")) {
        exportConfigs.failureDataFileMaxCapacity = exporterValue.at("failureDataFileMaxCapacity");
    }
    if (exporterValue.contains("enabledInstruments")) {
        for (auto &it : exporterValue.at("enabledInstruments").items()) {
            YRLOG_INFO("Enabled instrument: {}", it.value().dump());
            exportConfigs.enabledInstruments.insert(it.value().get<std::string>());
        }
    }
    return exportConfigs;
}

void MetricsAdaptor::CleanMetrics() noexcept
{
    std::lock_guard<std::mutex> lock(prometheus_pull_exporter_mutex_);
    if (prometheusPullExporter_ != nullptr) {
        prometheusPullExporter_->Shutdown();
        prometheusPullExporter_.reset();
    }
    Initialized_ = false;
    userEnable_ = false;
    metricSampleAllowAll_ = false;
    metricSampleEnabledInstruments_.clear();
    {
        std::lock_guard<std::mutex> l(instrument_kind_mutex_);
        instrumentKinds_.clear();
    }
    {
        std::lock_guard<std::mutex> l(gauge_mutex_);
        doubleGaugeMap_.clear();
        doubleGaugeSamples_.clear();
    }
    {
        std::lock_guard<std::mutex> l(uint64_counter_mutex_);
        uInt64CounterMap_.clear();
        uint64CounterSamples_.clear();
    }
    {
        std::lock_guard<std::mutex> l(double_counter_mutex_);
        doubleCounterMap_.clear();
        doubleCounterSamples_.clear();
    }
    {
        std::lock_guard<std::mutex> l(alarm_mutex_);
        alarmMap_.clear();
    }
    std::shared_ptr<MetricsApi::NullMeterProvider> null = nullptr;
    MetricsApi::Provider::SetMeterProvider(null);
}

bool MetricsAdaptor::MetricsEnabled() const
{
    return userEnable_ && Initialized_;
}

void MetricsAdaptor::AddMetricSampleEnabledInstruments(const MetricsSdk::ExportConfigs &exportConfigs)
{
    if (exportConfigs.enabledInstruments.empty()) {
        metricSampleAllowAll_ = true;
        return;
    }
    metricSampleEnabledInstruments_.insert(exportConfigs.enabledInstruments.begin(),
                                           exportConfigs.enabledInstruments.end());
}

bool MetricsAdaptor::IsMetricSampleEnabled(const std::string &name) const
{
    return metricSampleAllowAll_.load() || metricSampleEnabledInstruments_.count(name) > 0;
}

ErrorInfo MetricsAdaptor::MetricSampleNotEnabledError(const std::string &name) const
{
    return ErrorInfo(YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR, YR::Libruntime::ModuleCode::RUNTIME,
                     "metric sample is not enabled by global enabledInstruments: " + name);
}

ErrorInfo MetricsAdaptor::EventInstrumentStateError(const std::string &name) const
{
    return ErrorInfo(YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR, YR::Libruntime::ModuleCode::RUNTIME,
                     "event instrument does not support stateful operation: " + name);
}

ErrorInfo MetricsAdaptor::InstrumentKindConflictError(const std::string &name) const
{
    return ErrorInfo(YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR, YR::Libruntime::ModuleCode::RUNTIME,
                     "instrument kind conflicts with existing instrument: " + name);
}

ErrorInfo MetricsAdaptor::CheckInstrumentKind(const std::string &name,
                                              YR::Libruntime::InstrumentKind instrumentKind)
{
    std::lock_guard<std::mutex> l(instrument_kind_mutex_);
    auto it = instrumentKinds_.find(name);
    if (it != instrumentKinds_.end() && it->second != instrumentKind) {
        return InstrumentKindConflictError(name);
    }
    return ErrorInfo();
}

ErrorInfo MetricsAdaptor::CheckAndRecordInstrumentKind(const std::string &name,
                                                       YR::Libruntime::InstrumentKind instrumentKind)
{
    std::lock_guard<std::mutex> l(instrument_kind_mutex_);
    auto it = instrumentKinds_.find(name);
    if (it != instrumentKinds_.end()) {
        if (it->second != instrumentKind) {
            return InstrumentKindConflictError(name);
        }
        return ErrorInfo();
    }
    instrumentKinds_[name] = instrumentKind;
    return ErrorInfo();
}

ErrorInfo MetricsAdaptor::ValidateMetricOperation(const std::string &name,
                                                  YR::Libruntime::InstrumentKind instrumentKind,
                                                  MetricOperation operation)
{
    if (!MetricsEnabled()) {
        return ErrorInfo(YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR, YR::Libruntime::ModuleCode::RUNTIME,
                         "not enable metrics");
    }

    const bool isMetric = instrumentKind == YR::Libruntime::InstrumentKind::METRIC;
    if (!isMetric && operation != MetricOperation::RECORD) {
        return EventInstrumentStateError(name);
    }
    if (isMetric && !IsMetricSampleEnabled(name)) {
        return MetricSampleNotEnabledError(name);
    }
    if (operation == MetricOperation::READ) {
        return CheckInstrumentKind(name, instrumentKind);
    }
    return CheckAndRecordInstrumentKind(name, instrumentKind);
}

std::map<std::string, std::string> MetricsAdaptor::BuildPlatformLabels() const
{
    std::map<std::string, std::string> labels;
    const auto podName = Config::Instance().POD_NAME();
    if (!podName.empty()) {
        labels[POD_LABEL] = podName;
    } else if (const auto *envPodName = std::getenv(POD_NAME_ENV); envPodName != nullptr && *envPodName != '\0') {
        labels[POD_LABEL] = envPodName;
    }

    if (const auto *envNamespace = std::getenv(POD_NAMESPACE_ENV);
        envNamespace != nullptr && *envNamespace != '\0') {
        labels[NAMESPACE_LABEL] = envNamespace;
    }
    return labels;
}

std::map<std::string, std::string> MetricsAdaptor::CanonicalizeLabels(
    const std::unordered_map<std::string, std::string> &labels) const
{
    auto result = BuildPlatformLabels();
    for (const auto &[key, value] : labels) {
        result[key] = value;
    }
    return result;
}

MetricsSdk::PointLabels MetricsAdaptor::BuildPointLabels(const std::unordered_map<std::string, std::string> &labels)
    const
{
    MetricsSdk::PointLabels pointLabels;
    const auto canonicalized = CanonicalizeLabels(labels);
    for (const auto &[key, value] : canonicalized) {
        pointLabels.emplace_back(key, value);
    }
    return pointLabels;
}

std::string MetricsAdaptor::BuildMetricSampleKey(const std::string &name,
                                                 const std::map<std::string, std::string> &labels) const
{
    std::ostringstream oss;
    oss << name;
    for (const auto &[labelName, labelValue] : labels) {
        oss << '\n' << labelName << '=' << labelValue;
    }
    return oss.str();
}

template <typename Data, typename SampleMap, typename InstrumentMap, typename UpdateValue>
void MetricsAdaptor::UpdateMetricSample(const Data &data, SampleMap &samples, InstrumentMap &instruments,
                                        UpdateValue updateValue)
{
    auto labels = CanonicalizeLabels(data.labels);
    auto key = BuildMetricSampleKey(data.name, labels);
    auto &sample = samples[key];
    if (!sample.name.empty() && (sample.description != data.description || sample.unit != data.unit)) {
        instruments.erase(data.name);
        sample.description = data.description;
        sample.unit = data.unit;
        sample.labels = labels;
    }
    if (sample.name.empty()) {
        sample.name = data.name;
        sample.description = data.description;
        sample.unit = data.unit;
        sample.labels = labels;
    }
    updateValue(sample, data);
}

std::pair<ErrorInfo, double> MetricsAdaptor::GetGaugeSampleValue(const YR::Libruntime::GaugeData &gauge)
{
    std::lock_guard<std::mutex> l(gauge_mutex_);
    auto key = BuildMetricSampleKey(gauge.name, CanonicalizeLabels(gauge.labels));
    auto it = doubleGaugeSamples_.find(key);
    if (it == doubleGaugeSamples_.end()) {
        return std::make_pair(ErrorInfo(), 0);
    }
    return std::make_pair(ErrorInfo(), it->second.value);
}

std::pair<ErrorInfo, uint64_t> MetricsAdaptor::GetUInt64CounterSampleValue(
    const YR::Libruntime::UInt64CounterData &data)
{
    std::lock_guard<std::mutex> l(uint64_counter_mutex_);
    auto key = BuildMetricSampleKey(data.name, CanonicalizeLabels(data.labels));
    auto it = uint64CounterSamples_.find(key);
    if (it == uint64CounterSamples_.end()) {
        return std::make_pair(ErrorInfo(), 0);
    }
    return std::make_pair(ErrorInfo(), it->second.value);
}

std::pair<ErrorInfo, double> MetricsAdaptor::GetDoubleCounterSampleValue(
    const YR::Libruntime::DoubleCounterData &data)
{
    std::lock_guard<std::mutex> l(double_counter_mutex_);
    auto key = BuildMetricSampleKey(data.name, CanonicalizeLabels(data.labels));
    auto it = doubleCounterSamples_.find(key);
    if (it == doubleCounterSamples_.end()) {
        return std::make_pair(ErrorInfo(), 0);
    }
    return std::make_pair(ErrorInfo(), it->second.value);
}

ErrorInfo MetricsAdaptor::SetUInt64Counter(const YR::Libruntime::UInt64CounterData &data)
{
    const bool isMetric = data.instrumentKind == YR::Libruntime::InstrumentKind::METRIC;
    auto err = ValidateMetricOperation(data.name, data.instrumentKind, MetricOperation::RECORD);
    if (!err.OK()) {
        return err;
    }
    if (isMetric) {
        std::lock_guard<std::mutex> l(uint64_counter_mutex_);
        UpdateMetricSample(data, uint64CounterSamples_, uInt64CounterMap_,
                           [](auto &sample, const auto &data) { sample.value = data.value; });
    }
    return ReportUInt64Counter(data);
}

ErrorInfo MetricsAdaptor::ResetUInt64Counter(const YR::Libruntime::UInt64CounterData &data)
{
    auto err = ValidateMetricOperation(data.name, data.instrumentKind, MetricOperation::STATEFUL);
    if (!err.OK()) {
        return err;
    }
    {
        std::lock_guard<std::mutex> l(uint64_counter_mutex_);
        UpdateMetricSample(data, uint64CounterSamples_, uInt64CounterMap_,
                           [](auto &sample, const auto & /* data */) { sample.value = 0; });
    }
    return DoResetUInt64Counter(data);
}

ErrorInfo MetricsAdaptor::IncreaseUInt64Counter(const YR::Libruntime::UInt64CounterData &data)
{
    auto err = ValidateMetricOperation(data.name, data.instrumentKind, MetricOperation::STATEFUL);
    if (!err.OK()) {
        return err;
    }
    {
        std::lock_guard<std::mutex> l(uint64_counter_mutex_);
        UpdateMetricSample(data, uint64CounterSamples_, uInt64CounterMap_,
                           [](auto &sample, const auto &data) { sample.value += data.value; });
    }
    return DoIncreaseUInt64Counter(data);
}

std::pair<ErrorInfo, uint64_t> MetricsAdaptor::GetValueUInt64Counter(const YR::Libruntime::UInt64CounterData &data)
{
    auto err = ValidateMetricOperation(data.name, data.instrumentKind, MetricOperation::READ);
    if (!err.OK()) {
        return std::make_pair(err, 0);
    }
    return GetUInt64CounterSampleValue(data);
}

ErrorInfo MetricsAdaptor::ReportUInt64Counter(const YR::Libruntime::UInt64CounterData &data)
{
    std::lock_guard<std::mutex> l(uint64_counter_mutex_);
    auto err = InitUInt64Counter(data);
    if (!err.OK()) {
        return err;
    }
    auto labels = BuildPointLabels(data.labels);
    uInt64CounterMap_.find(data.name)->second->Set(data.value, labels);
    YRLOG_DEBUG("finished set uint64 counter value {}", data.value);
    return ErrorInfo();
}

ErrorInfo MetricsAdaptor::DoResetUInt64Counter(const YR::Libruntime::UInt64CounterData &data)
{
    std::lock_guard<std::mutex> l(uint64_counter_mutex_);
    auto err = InitUInt64Counter(data);
    if (!err.OK()) {
        return err;
    }
    auto labels = BuildPointLabels(data.labels);
    uInt64CounterMap_.find(data.name)->second->Set(0, labels);
    YRLOG_DEBUG("finished reset uint64 counter, name {}", data.name);
    return ErrorInfo();
}

ErrorInfo MetricsAdaptor::DoIncreaseUInt64Counter(const YR::Libruntime::UInt64CounterData &data)
{
    std::lock_guard<std::mutex> l(uint64_counter_mutex_);
    auto err = InitUInt64Counter(data);
    if (!err.OK()) {
        return err;
    }
    auto iter = uInt64CounterMap_.find(data.name);
    if (iter != uInt64CounterMap_.end()) {
        auto labels = BuildPointLabels(data.labels);
        const auto key = BuildMetricSampleKey(data.name, CanonicalizeLabels(data.labels));
        const auto sampleIt = uint64CounterSamples_.find(key);
        const auto current =
            sampleIt == uint64CounterSamples_.end() ? iter->second->GetValue() + data.value : sampleIt->second.value;
        iter->second->Set(current, labels);
        YRLOG_DEBUG("finished increase uint64 counter value {}", data.value);
    }
    return ErrorInfo();
}

std::pair<ErrorInfo, uint64_t> MetricsAdaptor::DoGetValueUInt64Counter(const YR::Libruntime::UInt64CounterData &data)
{
    std::lock_guard<std::mutex> l(uint64_counter_mutex_);
    auto err = InitUInt64Counter(data);
    if (!err.OK()) {
        return std::make_pair(err, 0);
    }
    auto val = uInt64CounterMap_.find(data.name)->second->GetValue();
    YRLOG_DEBUG("finished get value: {} of uint64 counter value", val);
    return std::make_pair(ErrorInfo(), val);
}

ErrorInfo MetricsAdaptor::InitUInt64Counter(const YR::Libruntime::UInt64CounterData &data)
{
    if (uInt64CounterMap_.find(data.name) != uInt64CounterMap_.end()) {
        return ErrorInfo();
    }
    auto provider = MetricsApi::Provider::GetMeterProvider();
    if (provider == nullptr) {
        YRLOG_ERROR("Metrics provider is null");
        return ErrorInfo(YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR, YR::Libruntime::ModuleCode::RUNTIME,
                         "there is no metrics provider ");
    }
    std::shared_ptr<MetricsApi::Meter> meter = provider->GetMeter("uinit64_counter_meter");
    if (meter == nullptr) {
        YRLOG_ERROR("Metrics meter is null");
        return ErrorInfo(YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR, YR::Libruntime::ModuleCode::RUNTIME,
                         "there is no metrics meter");
    }
    auto uInt64Counter = meter->CreateUInt64Counter(data.name, data.description, data.unit);
    uInt64CounterMap_[data.name] = std::move(uInt64Counter);
    return ErrorInfo();
}

ErrorInfo MetricsAdaptor::SetDoubleCounter(const YR::Libruntime::DoubleCounterData &data)
{
    const bool isMetric = data.instrumentKind == YR::Libruntime::InstrumentKind::METRIC;
    auto err = ValidateMetricOperation(data.name, data.instrumentKind, MetricOperation::RECORD);
    if (!err.OK()) {
        return err;
    }
    if (isMetric) {
        std::lock_guard<std::mutex> l(double_counter_mutex_);
        UpdateMetricSample(data, doubleCounterSamples_, doubleCounterMap_,
                           [](auto &sample, const auto &data) { sample.value = data.value; });
    }
    return ReportDoubleCounter(data);
}

ErrorInfo MetricsAdaptor::ResetDoubleCounter(const YR::Libruntime::DoubleCounterData &data)
{
    auto err = ValidateMetricOperation(data.name, data.instrumentKind, MetricOperation::STATEFUL);
    if (!err.OK()) {
        return err;
    }
    {
        std::lock_guard<std::mutex> l(double_counter_mutex_);
        UpdateMetricSample(data, doubleCounterSamples_, doubleCounterMap_,
                           [](auto &sample, const auto & /* data */) { sample.value = 0; });
    }
    return DoResetDoubleCounter(data);
}

ErrorInfo MetricsAdaptor::IncreaseDoubleCounter(const YR::Libruntime::DoubleCounterData &data)
{
    auto err = ValidateMetricOperation(data.name, data.instrumentKind, MetricOperation::STATEFUL);
    if (!err.OK()) {
        return err;
    }
    {
        std::lock_guard<std::mutex> l(double_counter_mutex_);
        UpdateMetricSample(data, doubleCounterSamples_, doubleCounterMap_,
                           [](auto &sample, const auto &data) { sample.value += data.value; });
    }
    return DoIncreaseDoubleCounter(data);
}

std::pair<ErrorInfo, double> MetricsAdaptor::GetValueDoubleCounter(const YR::Libruntime::DoubleCounterData &data)
{
    auto err = ValidateMetricOperation(data.name, data.instrumentKind, MetricOperation::READ);
    if (!err.OK()) {
        return std::make_pair(err, 0);
    }
    return GetDoubleCounterSampleValue(data);
}

ErrorInfo MetricsAdaptor::ReportDoubleCounter(const YR::Libruntime::DoubleCounterData &data)
{
    std::lock_guard<std::mutex> l(double_counter_mutex_);
    auto err = InitDoubleCounter(data);
    if (!err.OK()) {
        return err;
    }
    auto labels = BuildPointLabels(data.labels);
    auto it = doubleCounterMap_.find(data.name);
    if (it != doubleCounterMap_.end()) {
        it->second->Set(data.value, labels);
    }
    YRLOG_DEBUG("finished set double counter value {}", data.value);
    return ErrorInfo();
}

ErrorInfo MetricsAdaptor::DoResetDoubleCounter(const YR::Libruntime::DoubleCounterData &data)
{
    std::lock_guard<std::mutex> l(double_counter_mutex_);
    auto err = InitDoubleCounter(data);
    if (!err.OK()) {
        return err;
    }
    auto it = doubleCounterMap_.find(data.name);
    if (it != doubleCounterMap_.end()) {
        auto labels = BuildPointLabels(data.labels);
        it->second->Set(0, labels);
    }
    YRLOG_DEBUG("finished reset double counter, name: {}", data.name);
    return ErrorInfo();
}

ErrorInfo MetricsAdaptor::DoIncreaseDoubleCounter(const YR::Libruntime::DoubleCounterData &data)
{
    std::lock_guard<std::mutex> l(double_counter_mutex_);
    auto err = InitDoubleCounter(data);
    if (!err.OK()) {
        return err;
    }
    auto it = doubleCounterMap_.find(data.name);
    if (it != doubleCounterMap_.end()) {
        auto labels = BuildPointLabels(data.labels);
        const auto key = BuildMetricSampleKey(data.name, CanonicalizeLabels(data.labels));
        const auto sampleIt = doubleCounterSamples_.find(key);
        const auto current =
            sampleIt == doubleCounterSamples_.end() ? it->second->GetValue() + data.value : sampleIt->second.value;
        it->second->Set(current, labels);
    }
    YRLOG_DEBUG("finished increase double counter value {}", data.value);
    return ErrorInfo();
}

std::pair<ErrorInfo, double> MetricsAdaptor::DoGetValueDoubleCounter(const YR::Libruntime::DoubleCounterData &data)
{
    std::lock_guard<std::mutex> l(double_counter_mutex_);
    auto err = InitDoubleCounter(data);
    if (!err.OK()) {
        return std::make_pair(err, 0);
    }
    auto it = doubleCounterMap_.find(data.name);
    if (it != doubleCounterMap_.end()) {
        auto val = it->second->GetValue();
        YRLOG_DEBUG("finished get value: {} of double counter", val);
        return std::make_pair(ErrorInfo(), val);
    }
    return std::make_pair(ErrorInfo(), 0);
}

ErrorInfo MetricsAdaptor::InitDoubleCounter(const YR::Libruntime::DoubleCounterData &data)
{
    if (doubleCounterMap_.find(data.name) != doubleCounterMap_.end()) {
        return ErrorInfo();
    }
    auto provider = MetricsApi::Provider::GetMeterProvider();
    if (provider == nullptr) {
        YRLOG_ERROR("Metrics provider is null");
        return ErrorInfo(YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR, YR::Libruntime::ModuleCode::RUNTIME,
                         "there is no metrics provider ");
    }
    std::shared_ptr<MetricsApi::Meter> meter = provider->GetMeter("double_counter_meter");
    if (meter == nullptr) {
        YRLOG_ERROR("Metrics meter is null");
        return ErrorInfo(YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR, YR::Libruntime::ModuleCode::RUNTIME,
                         "there is no metrics meter");
    }
    auto doubleCounter = meter->CreateDoubleCounter(data.name, data.description, data.unit);
    doubleCounterMap_[data.name] = std::move(doubleCounter);
    return ErrorInfo();
}

ErrorInfo MetricsAdaptor::SetGauge(const YR::Libruntime::GaugeData &gauge)
{
    const bool isMetric = gauge.instrumentKind == YR::Libruntime::InstrumentKind::METRIC;
    auto err = ValidateMetricOperation(gauge.name, gauge.instrumentKind, MetricOperation::RECORD);
    if (!err.OK()) {
        return err;
    }
    if (isMetric) {
        std::lock_guard<std::mutex> l(gauge_mutex_);
        UpdateMetricSample(gauge, doubleGaugeSamples_, doubleGaugeMap_,
                           [](auto &sample, const auto &data) { sample.value = data.value; });
    }
    return ReportDoubleGauge(gauge);
}

ErrorInfo MetricsAdaptor::IncreaseGauge(const YR::Libruntime::GaugeData &gauge)
{
    YR::Libruntime::GaugeData currentGauge = gauge;
    auto err = ValidateMetricOperation(gauge.name, gauge.instrumentKind, MetricOperation::STATEFUL);
    if (!err.OK()) {
        return err;
    }
    {
        std::lock_guard<std::mutex> l(gauge_mutex_);
        UpdateMetricSample(gauge, doubleGaugeSamples_, doubleGaugeMap_,
                           [](auto &sample, const auto &data) { sample.value += data.value; });
        const auto key = BuildMetricSampleKey(gauge.name, CanonicalizeLabels(gauge.labels));
        const auto sampleIt = doubleGaugeSamples_.find(key);
        currentGauge.value = sampleIt == doubleGaugeSamples_.end() ? gauge.value : sampleIt->second.value;
    }
    return ReportDoubleGauge(currentGauge);
}

ErrorInfo MetricsAdaptor::DecreaseGauge(const YR::Libruntime::GaugeData &gauge)
{
    YR::Libruntime::GaugeData currentGauge = gauge;
    auto err = ValidateMetricOperation(gauge.name, gauge.instrumentKind, MetricOperation::STATEFUL);
    if (!err.OK()) {
        return err;
    }
    {
        std::lock_guard<std::mutex> l(gauge_mutex_);
        UpdateMetricSample(gauge, doubleGaugeSamples_, doubleGaugeMap_,
                           [](auto &sample, const auto &data) {
                               sample.value -= data.value;
                               if (sample.value < 0) {
                                   sample.value = 0;
                               }
                           });
        const auto key = BuildMetricSampleKey(gauge.name, CanonicalizeLabels(gauge.labels));
        const auto sampleIt = doubleGaugeSamples_.find(key);
        currentGauge.value = sampleIt == doubleGaugeSamples_.end() ? gauge.value : sampleIt->second.value;
    }
    return ReportDoubleGauge(currentGauge);
}

std::pair<ErrorInfo, double> MetricsAdaptor::GetValueGauge(const YR::Libruntime::GaugeData &gauge)
{
    auto err = ValidateMetricOperation(gauge.name, gauge.instrumentKind, MetricOperation::READ);
    if (!err.OK()) {
        return std::make_pair(err, 0);
    }
    return GetGaugeSampleValue(gauge);
}

ErrorInfo MetricsAdaptor::ReportMetrics(const YR::Libruntime::GaugeData &gauge)
{
    const bool isMetric = gauge.instrumentKind == YR::Libruntime::InstrumentKind::METRIC;
    auto err = ValidateMetricOperation(gauge.name, gauge.instrumentKind, MetricOperation::RECORD);
    if (!err.OK()) {
        return err;
    }
    if (isMetric) {
        std::lock_guard<std::mutex> l(gauge_mutex_);
        UpdateMetricSample(gauge, doubleGaugeSamples_, doubleGaugeMap_,
                           [](auto &sample, const auto &data) { sample.value = data.value; });
    }
    return ReportDoubleGauge(gauge);
}

ErrorInfo MetricsAdaptor::ReportGauge(const YR::Libruntime::GaugeData &gauge)
{
    return SetGauge(gauge);
}

ErrorInfo MetricsAdaptor::ReportDoubleGauge(const YR::Libruntime::GaugeData &gauge)
{
    std::unique_lock<std::mutex> l(gauge_mutex_);
    auto err = InitDoubleGauge(gauge);
    if (!err.OK()) {
        l.unlock();
        return err;
    }
    if (doubleGaugeMap_.find(gauge.name) == doubleGaugeMap_.end()) {
        l.unlock();
        return ErrorInfo(YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR, YR::Libruntime::ModuleCode::RUNTIME,
                         "can not find gauge name");
    }
    auto it = doubleGaugeMap_.find(gauge.name);
    l.unlock();
    auto labels = BuildPointLabels(gauge.labels);
    it->second->Set(gauge.value, labels);
    YRLOG_DEBUG("finished set gauge value {}", gauge.value);
    return ErrorInfo();
}

ErrorInfo MetricsAdaptor::InitDoubleGauge(const YR::Libruntime::GaugeData &gauge)
{
    if (doubleGaugeMap_.find(gauge.name) != doubleGaugeMap_.end()) {
        return ErrorInfo();
    }
    auto provider = MetricsApi::Provider::GetMeterProvider();
    if (provider == nullptr) {
        return ErrorInfo(YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR, YR::Libruntime::ModuleCode::RUNTIME,
                         "there is no metrics provider ");
    }
    std::shared_ptr<MetricsApi::Meter> meter = provider->GetMeter("gauge_meter");
    if (meter == nullptr) {
        return ErrorInfo(YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR, YR::Libruntime::ModuleCode::RUNTIME,
                         "there is no metrics meter");
    }
    auto gaugeData = meter->CreateDoubleGauge(gauge.name, gauge.description, gauge.unit);
    doubleGaugeMap_[gauge.name] = std::move(gaugeData);
    return ErrorInfo();
}

ErrorInfo MetricsAdaptor::SetAlarm(const std::string &name, const std::string &description,
                                   const YR::Libruntime::AlarmInfo &alarmInfo)
{
    if (userEnable_ && Initialized_) {
        return ReportAlarm(name, description, alarmInfo);
    }
    YRLOG_ERROR("failed to set alarm, userEnable: {}, initialized: {}", userEnable_, Initialized_);
    return ErrorInfo(YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR, YR::Libruntime::ModuleCode::RUNTIME,
                     "not enable metrics");
}

ErrorInfo MetricsAdaptor::ReportAlarm(const std::string &name, const std::string &description,
                                      const YR::Libruntime::AlarmInfo &alarmInfo)
{
    std::lock_guard<std::mutex> l(alarm_mutex_);
    auto err = InitAlarm(name, description);
    if (!err.OK()) {
        return err;
    }
    if (alarmMap_.find(name) == alarmMap_.end()) {
        return ErrorInfo(YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR, YR::Libruntime::ModuleCode::RUNTIME,
                         "can not find alarm name");
    }
    MetricsApi::AlarmInfo metricsAlarmInfo;
    metricsAlarmInfo.id = alarmInfo.id;
    metricsAlarmInfo.alarmName = alarmInfo.alarmName;
    metricsAlarmInfo.alarmSeverity = static_cast<MetricsApi::AlarmSeverity>(alarmInfo.alarmSeverity);
    metricsAlarmInfo.locationInfo = alarmInfo.locationInfo;
    metricsAlarmInfo.cause = alarmInfo.cause;
    metricsAlarmInfo.startsAt =
        alarmInfo.startsAt == DEFAULT_ALARM_TIMESTAMP
            ? std::chrono::duration_cast<std::chrono::seconds>(std::chrono::system_clock::now().time_since_epoch())
                  .count()
            : alarmInfo.startsAt;
    metricsAlarmInfo.endsAt = alarmInfo.endsAt;
    metricsAlarmInfo.timeout = alarmInfo.timeout;
    for (auto &it : alarmInfo.customOptions) {
        metricsAlarmInfo.customOptions[it.first] = it.second;
    }
    alarmMap_.find(name)->second->Set(metricsAlarmInfo);
    YRLOG_DEBUG("finished set alarm name {}, location info: {}, cause: {}", metricsAlarmInfo.alarmName,
                metricsAlarmInfo.locationInfo, metricsAlarmInfo.cause);
    return ErrorInfo();
}

ErrorInfo MetricsAdaptor::InitAlarm(const std::string &name, const std::string &description)
{
    if (alarmMap_.find(name) != alarmMap_.end()) {
        return ErrorInfo();
    }
    auto provider = MetricsApi::Provider::GetMeterProvider();
    if (provider == nullptr) {
        YRLOG_ERROR("Metrics provider is null");
        return ErrorInfo(YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR, YR::Libruntime::ModuleCode::RUNTIME,
                         "there is no metrics provider ");
    }
    std::shared_ptr<MetricsApi::Meter> meter = provider->GetMeter("alarm_meter");
    if (meter == nullptr) {
        YRLOG_ERROR("Metrics meter is null");
        return ErrorInfo(YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR, YR::Libruntime::ModuleCode::RUNTIME,
                         "there is no metrics meter");
    }
    auto alarm = meter->CreateAlarm(name, description);
    alarmMap_[name] = std::move(alarm);
    return ErrorInfo();
}

std::shared_ptr<MetricsExporters::Exporter> MetricsAdaptor::InitFileExporter(
    const std::string &backendKey, const std::string &backendName, const nlohmann::json &exporterValue,
    const std::function<std::string(std::string)> &getFileName)
{
    YRLOG_DEBUG("add exporter {} for backend {} of {}", FILE_EXPORTER, backendKey, backendName);
    if (exporterValue.find("enable") == exporterValue.end() || !exporterValue.at("enable").get<bool>()) {
        YRLOG_DEBUG("metrics exporter {} for backend {} of {} is not enabled", FILE_EXPORTER, backendKey, backendName);
        return nullptr;
    }
    std::string initConfig;
    if (exporterValue.find("initConfig") != exporterValue.end()) {
        auto initConfigJson = exporterValue.at("initConfig");
        if (initConfigJson.find("fileDir") == initConfigJson.end() ||
            initConfigJson.at("fileDir").get<std::string>().empty()) {
            YRLOG_DEBUG("not find the metrics exporter file path, use the log path: {}", GetContextValue("log_dir"));
            initConfigJson["fileDir"] = GetContextValue("log_dir");
        }
        if (!YR::utility::ExistPath(initConfigJson.at("fileDir")) &&
            !YR::utility::Mkdir(initConfigJson.at("fileDir"))) {
            YRLOG_ERROR("failed to mkdir{} for exporter {} for backend {} of {}", initConfigJson.at("fileDir").dump(),
                        FILE_EXPORTER, backendKey, backendName);
            return nullptr;
        }
        initConfigJson["fileName"] = getFileName(backendName);
        try {
            initConfig = initConfigJson.dump();
        } catch (std::exception &e) {
            YRLOG_ERROR("dump initConfigJson failed, error: {}", e.what());
            return nullptr;
        }
    }
    YRLOG_INFO("metrics exporter {} for backend {} of {}, init config: {}", FILE_EXPORTER, backendKey, backendName,
               initConfig);
    std::string error;
    return MetricsPlugin::LoadExporterFromLibrary(GetLibraryPath(FILE_EXPORTER), initConfig, error);
}

std::string MetricsAdaptor::GetMetricsFilesName(const std::string &backendName)
{
    // file reporting is not supported currently,this function is not implemented.
    if (backendName == "ds_alarm") {
        return backendName + ".alarm.dat";
    }
    return backendName + "-metrics.data";
}
}  // namespace Libruntime
}  // namespace YR
