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

#include <gmock/gmock.h>
#include <gtest/gtest.h>
#include <cstdlib>
#include <string>
#include <unistd.h>

#define private public
#include "metrics/api/provider.h"
#include "metrics/exporters/exporter.h"
#include "metrics/sdk/immediately_export_processor.h"
#include "metrics/sdk/meter_provider.h"
#include "src/dto/config.h"
#include "src/libruntime/err_type.h"
#include "src/libruntime/metricsadaptor/metrics_adaptor.h"
#include "src/utility/logger/fileutils.h"
#include "src/utility/logger/logger.h"

using namespace testing;
using namespace YR::utility;
using namespace YR::Libruntime;
namespace MetricsApi = observability::api::metrics;
namespace MetricsSdk = observability::sdk::metrics;
namespace MetricsExporters = observability::exporters::metrics;
namespace YR {
namespace test {

namespace {
constexpr uint16_t DISABLED_PROMETHEUS_PULL_EXPORTER_PORT = 0;

class FakeExporter : public MetricsExporters::Exporter {
public:
    MetricsExporters::ExportResult Export(
        const std::vector<observability::sdk::metrics::MetricData> & /* data */) noexcept override
    {
        return MetricsExporters::ExportResult::SUCCESS;
    }

    observability::sdk::metrics::AggregationTemporality GetAggregationTemporality(
        observability::sdk::metrics::InstrumentType /* instrumentType */) const noexcept override
    {
        return observability::sdk::metrics::AggregationTemporality::CUMULATIVE;
    }

    bool ForceFlush(std::chrono::microseconds /* timeout */) noexcept override
    {
        return true;
    }

    bool Shutdown(std::chrono::microseconds /* timeout */) noexcept override
    {
        return true;
    }

    void RegisterOnHealthChangeCb(const std::function<void(bool)> & /* onChange */) noexcept override {}
};

class ScopedPlatformEnv {
public:
    ScopedPlatformEnv()
    {
        setenv("POD_NAME", "runtime-pod", 1);
        setenv("POD_NAMESPACE", "runtime-namespace", 1);
        YR::Libruntime::Config::c = YR::Libruntime::Config();
    }

    ~ScopedPlatformEnv()
    {
        unsetenv("POD_NAME");
        unsetenv("POD_NAMESPACE");
        YR::Libruntime::Config::c = YR::Libruntime::Config();
    }
};
}  // namespace

nlohmann::json GetValidConfig()
{
    const std::string str = R"(
{
    "backends": [
        {
            "immediatelyExport": {
                "name": "CAAS_Alarm",
                "enable": true,
                "custom": {
                    "labels": {
                        "site": "",
                        "tenant_id": "",
                        "application_id": "",
                        "service_id": ""
                    }
                },
                "exporters": []
            }
        },
        {
            "immediatelyExport": {
                "name": "LingYun",
                "enable": true,
                "exporters": []
            }
        }
    ]
}
    )";
    return nlohmann::json::parse(str);
}

nlohmann::json GetUnsupportedConfig()
{
    const std::string str = R"(
{
    "backends": [
        {
            "batchExport": {"name": "CAAS_Alarm"}
        }
    ]
}
    )";
    return nlohmann::json::parse(str);
}

nlohmann::json GetInvalidConfig()
{
    const std::string str = R"(
{
    "invalid": []
}
    )";
    return nlohmann::json::parse(str);
}

nlohmann::json GetImmedExportNotEnableConfig()
{
    const std::string str = R"(
{
    "backends": [
        {
            "immediatelyExport": {
                "name": "LingYun",
                "enable": false,
                "exporters": [
                    {
                        "prometheusPushExporter": {
                            "enable": true,
                            "ip": "127.0.0.1",
                            "port": 9091
                        }
                    }
                ]
            }
        }
    ]
}
    )";
    return nlohmann::json::parse(str);
}

nlohmann::json GetPromExportNotEnableConfig()
{
    const std::string str = R"(
{
    "backends": [
        {
            "immediatelyExport": {
                "name": "LingYun",
                "enable": true,
                "exporters": [
                    {
                        "prometheusPushExporter": {
                            "enable": false,
                            "ip": "127.0.0.1",
                            "port": 9091
                        }
                    }
                ]
            }
        }
    ]
}
    )";
    return nlohmann::json::parse(str);
}

nlohmann::json GetPrometheusPushExporterConfig()
{
    std::string jsonStr = R"(
{
    "enable": true,
    "initConfig": {
        "ip": "x",
        "port": 0
    }
}
    )";
    return nlohmann::json::parse(jsonStr);
}

nlohmann::json GetExportConfigs()
{
    std::string jsonStr = R"(
{
    "enable": true,
    "enabledInstruments": ["name"],
    "batchSize": 5,
    "initConfig": {
        "ip": "127.0.0.1",
        "port": 31061
    }
}
    )";
    return nlohmann::json::parse(jsonStr);
}

nlohmann::json GetPrometheusPullExporterSslConfig()
{
    nlohmann::json config = {
        {"backends",
         {{
             {"immediatelyExport",
              {
                  {"name", "Runtime"},
                  {"enable", true},
                  {"exporters",
                   {{
                       {"prometheusPullExporter",
                        {
                            {"enable", false},
                            {"enabledInstruments", {"yr_custom_concurrent_num", "yr_custom_invoke_num"}},
                            {"initConfig",
                             {
                                 {"ip", "127.0.0.1"},
                                 {"port", DISABLED_PROMETHEUS_PULL_EXPORTER_PORT},
                                 {"metricsPath", "/metrics"},
                                 {"isSSLEnable", true},
                                 {"mutualTlsEnable", true},
                                 {"rootCertFile", "/tmp/root.crt"},
                                 {"certFile", "/tmp/server.crt"},
                                 {"keyFile", "/tmp/server.key"},
                                 {"passphrase", "secret"},
                             }},
                        }},
                   }}},
              }},
         }}}
    };
    return config;
}

std::shared_ptr<MetricsAdaptor> BuildMockInitializedMetricsAdaptor()
{
    auto metricsAdaptor = std::make_shared<MetricsAdaptor>();
    auto provider = std::make_shared<MetricsSdk::MeterProvider>(MetricsSdk::LiteBusParams{});
    MetricsSdk::ExportConfigs exportConfigs;
    exportConfigs.exporterName = "mock";
    exportConfigs.exportMode = MetricsSdk::ExportMode::IMMEDIATELY;
    auto exporter = std::make_shared<FakeExporter>();
    provider->AddMetricProcessor(std::make_shared<MetricsSdk::ImmediatelyExportProcessor>(std::move(exporter),
                                                                                          exportConfigs));
    MetricsApi::Provider::SetMeterProvider(provider);
    metricsAdaptor->userEnable_ = true;
    metricsAdaptor->Initialized_ = true;
    metricsAdaptor->metricSampleEnabledInstruments_ = {
        "name", "yr_custom_concurrent_num", "yr_custom_invoke_num"
    };
    return metricsAdaptor;
}

std::shared_ptr<MetricsAdaptor> BuildSampleOnlyMetricsAdaptor()
{
    auto metricsAdaptor = BuildMockInitializedMetricsAdaptor();
    metricsAdaptor->metricSampleEnabledInstruments_.insert("double_counter_sample");
    return metricsAdaptor;
}

class MetricsAdaptorTest : public testing::Test {
public:
    MetricsAdaptorTest(){};
    ~MetricsAdaptorTest(){};
    void SetUp() override
    {
        Mkdir("/tmp/log");
        LogParam g_logParam = {
            .logLevel = "DEBUG",
            .logDir = "/tmp/log",
            .nodeName = "test-runtime",
            .modelName = "test",
            .maxSize = 100,
            .maxFiles = 1,
            .logFileWithTime = false,
            .logBufSecs = 30,
            .maxAsyncQueueSize = 1048510,
            .asyncThreadCount = 1,
            .alsoLog2Stderr = true,
        };
        InitLog(g_logParam);
    }
    void TearDown() override {}

    std::string config;

private:
    pthread_t tids[1];
    int port = 22222;
};

TEST_F(MetricsAdaptorTest, InitSuccessullyTest)
{
    setenv("YR_SSL_ENABLE", "true", 1);
    setenv("YR_SSL_PASSPHRASE", "YR_SSL_PASSPHRASE", 1);
    Config::c = Config();
    auto nullMeterProvider = MetricsApi::Provider::GetMeterProvider();
    auto jsonStr = GetValidConfig();
    auto metricsAdaptor = std::make_shared<MetricsAdaptor>();
    metricsAdaptor->Init(jsonStr, true);
    EXPECT_NE(MetricsApi::Provider::GetMeterProvider(), nullMeterProvider);
    metricsAdaptor->CleanMetrics();
    EXPECT_EQ(MetricsApi::Provider::GetMeterProvider(), nullptr);
    unsetenv("YR_SSL_ENABLE");
    unsetenv("YR_SSL_PASSPHRASE");
}

TEST_F(MetricsAdaptorTest, UnsupportedInitTest)
{
    Config::c = Config();
    auto nullMeterProvider = MetricsApi::Provider::GetMeterProvider();
    auto jsonStr = GetUnsupportedConfig();
    auto metricsAdaptor = std::make_shared<MetricsAdaptor>();
    metricsAdaptor->Init(jsonStr, true);
    EXPECT_NE(MetricsApi::Provider::GetMeterProvider(), nullMeterProvider);
    metricsAdaptor->CleanMetrics();
    EXPECT_EQ(MetricsApi::Provider::GetMeterProvider(), nullptr);
}

TEST_F(MetricsAdaptorTest, InvalidInitTest)
{
    Config::c = Config();
    auto jsonStr = GetInvalidConfig();
    auto metricsAdaptor = std::make_shared<MetricsAdaptor>();
    metricsAdaptor->Init(jsonStr, true);
    metricsAdaptor->CleanMetrics();
    EXPECT_EQ(MetricsApi::Provider::GetMeterProvider(), nullptr);
}

TEST_F(MetricsAdaptorTest, InitNotEnableTest)
{
    Config::c = Config();
    auto nullMeterProvider = MetricsApi::Provider::GetMeterProvider();
    auto jsonStr = GetImmedExportNotEnableConfig();
    auto metricsAdaptor = std::make_shared<MetricsAdaptor>();
    metricsAdaptor->Init(jsonStr, true);
    EXPECT_NE(MetricsApi::Provider::GetMeterProvider(), nullMeterProvider);
    metricsAdaptor->CleanMetrics();
    EXPECT_EQ(MetricsApi::Provider::GetMeterProvider(), nullptr);

    auto jsonStr2 = GetPromExportNotEnableConfig();
    auto metricsAdaptor2 = std::make_shared<MetricsAdaptor>();
    metricsAdaptor2->Init(jsonStr2, true);
    EXPECT_NE(MetricsApi::Provider::GetMeterProvider(), nullMeterProvider);
    metricsAdaptor2->CleanMetrics();
    EXPECT_EQ(MetricsApi::Provider::GetMeterProvider(), nullptr);
}

TEST_F(MetricsAdaptorTest, DoubleGaugeTest)
{
    Config::c = Config();
    auto metricsAdaptor = BuildMockInitializedMetricsAdaptor();
    YR::Libruntime::GaugeData gauge;
    gauge.name = "name";
    gauge.description = "desc";
    gauge.unit = "unit";
    gauge.value = 1.11;
    auto err = metricsAdaptor->ReportMetrics(gauge);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_OK);
    err = metricsAdaptor->ReportGauge(gauge);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_OK);
    metricsAdaptor->CleanMetrics();
    EXPECT_EQ(MetricsApi::Provider::GetMeterProvider(), nullptr);
}

TEST_F(MetricsAdaptorTest, SetAlarmTest)
{
    Config::c = Config();
    auto metricsAdaptor = BuildMockInitializedMetricsAdaptor();
    YR::Libruntime::AlarmInfo alarmInfo;
    alarmInfo.alarmName = "name";
    alarmInfo.locationInfo = "info";
    alarmInfo.cause = "cause";
    auto err = metricsAdaptor->SetAlarm("name", "desc", alarmInfo);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_OK);
    err = metricsAdaptor->SetAlarm("name", "desc", alarmInfo);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_OK);
    metricsAdaptor->CleanMetrics();
    EXPECT_EQ(MetricsApi::Provider::GetMeterProvider(), nullptr);
}

TEST_F(MetricsAdaptorTest, DoubleCounterTest)
{
    Config::c = Config();
    auto metricsAdaptor = BuildMockInitializedMetricsAdaptor();
    YR::Libruntime::DoubleCounterData data;
    data.name = "name";
    data.description = "desc";
    data.unit = "unit";
    data.value = 1.11;
    auto err = metricsAdaptor->SetDoubleCounter(data);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_OK);
    auto res = metricsAdaptor->GetValueDoubleCounter(data);
    EXPECT_EQ(res.second, 1.11);
    err = metricsAdaptor->IncreaseDoubleCounter(data);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_OK);
    res = metricsAdaptor->GetValueDoubleCounter(data);
    EXPECT_EQ(res.second, 2.22);
    err = metricsAdaptor->ResetDoubleCounter(data);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_OK);
    res = metricsAdaptor->GetValueDoubleCounter(data);
    EXPECT_EQ(res.second, 0);
    metricsAdaptor->CleanMetrics();
    EXPECT_EQ(MetricsApi::Provider::GetMeterProvider(), nullptr);
}

TEST_F(MetricsAdaptorTest, DoubleCounterSampleValueTest)
{
    Config::c = Config();
    auto metricsAdaptor = BuildSampleOnlyMetricsAdaptor();
    YR::Libruntime::DoubleCounterData data;
    data.name = "double_counter_sample";
    data.description = "desc";
    data.unit = "unit";
    data.value = 1.25;

    auto emptyValue = metricsAdaptor->GetDoubleCounterSampleValue(data);
    ASSERT_TRUE(emptyValue.first.OK());
    ASSERT_EQ(emptyValue.second, 0);

    ASSERT_EQ(metricsAdaptor->SetDoubleCounter(data).Code(), YR::Libruntime::ErrorCode::ERR_OK);
    data.value = 2.5;
    ASSERT_EQ(metricsAdaptor->IncreaseDoubleCounter(data).Code(), YR::Libruntime::ErrorCode::ERR_OK);
    auto currentValue = metricsAdaptor->GetDoubleCounterSampleValue(data);
    ASSERT_TRUE(currentValue.first.OK());
    ASSERT_EQ(currentValue.second, 3.75);

    ASSERT_EQ(metricsAdaptor->ResetDoubleCounter(data).Code(), YR::Libruntime::ErrorCode::ERR_OK);
    auto resetValue = metricsAdaptor->GetDoubleCounterSampleValue(data);
    ASSERT_TRUE(resetValue.first.OK());
    ASSERT_EQ(resetValue.second, 0);
}

TEST_F(MetricsAdaptorTest, UInt64CounterTest)
{
    Config::c = Config();
    auto metricsAdaptor = BuildMockInitializedMetricsAdaptor();
    YR::Libruntime::UInt64CounterData data;
    data.name = "name";
    data.description = "desc";
    data.unit = "unit";
    data.value = 1;
    auto err = metricsAdaptor->SetUInt64Counter(data);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_OK);
    auto res = metricsAdaptor->GetValueUInt64Counter(data);
    EXPECT_EQ(res.second, 1);
    err = metricsAdaptor->IncreaseUInt64Counter(data);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_OK);
    res = metricsAdaptor->GetValueUInt64Counter(data);
    EXPECT_EQ(res.second, 2);
    err = metricsAdaptor->ResetUInt64Counter(data);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_OK);
    res = metricsAdaptor->GetValueUInt64Counter(data);
    EXPECT_EQ(res.second, 0);
    metricsAdaptor->CleanMetrics();
    EXPECT_EQ(MetricsApi::Provider::GetMeterProvider(), nullptr);
}

TEST_F(MetricsAdaptorTest, DecreaseGaugeSampleOnlyTest)
{
    Config::c = Config();
    auto metricsAdaptor = BuildSampleOnlyMetricsAdaptor();
    YR::Libruntime::GaugeData gauge;
    gauge.name = "yr_custom_concurrent_num";
    gauge.description = "custom concurrent";
    gauge.unit = "count";
    gauge.value = 5;
    ASSERT_EQ(metricsAdaptor->SetGauge(gauge).Code(), YR::Libruntime::ErrorCode::ERR_OK);

    gauge.value = 2;
    ASSERT_EQ(metricsAdaptor->DecreaseGauge(gauge).Code(), YR::Libruntime::ErrorCode::ERR_OK);
    auto decreasedValue = metricsAdaptor->GetValueGauge(gauge);
    ASSERT_TRUE(decreasedValue.first.OK());
    ASSERT_EQ(decreasedValue.second, 3);

    gauge.value = 10;
    ASSERT_EQ(metricsAdaptor->DecreaseGauge(gauge).Code(), YR::Libruntime::ErrorCode::ERR_OK);
    auto clampedValue = metricsAdaptor->GetValueGauge(gauge);
    ASSERT_TRUE(clampedValue.first.OK());
    ASSERT_EQ(clampedValue.second, 0);
}

TEST_F(MetricsAdaptorTest, MetricsFailedTest)
{
    auto metricsAdaptor = std::make_shared<MetricsAdaptor>();
    YR::Libruntime::UInt64CounterData data;
    auto err = metricsAdaptor->SetUInt64Counter(data);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);
    err = metricsAdaptor->IncreaseUInt64Counter(data);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);
    err = metricsAdaptor->ResetUInt64Counter(data);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);
    auto res = metricsAdaptor->GetValueUInt64Counter(data);
    EXPECT_EQ(res.first.Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);

    YR::Libruntime::DoubleCounterData data2;
    err = metricsAdaptor->SetDoubleCounter(data2);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);
    err = metricsAdaptor->IncreaseDoubleCounter(data2);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);
    err = metricsAdaptor->ResetDoubleCounter(data2);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);
    auto res2 = metricsAdaptor->GetValueDoubleCounter(data2);
    EXPECT_EQ(res2.first.Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);

    YR::Libruntime::AlarmInfo alarmInfo;
    YR::Libruntime::GaugeData gauge;
    err = metricsAdaptor->SetAlarm("name", "desc", alarmInfo);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);
    err = metricsAdaptor->ReportMetrics(gauge);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);
    err = metricsAdaptor->ReportGauge(gauge);
    EXPECT_EQ(err.Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);
}

TEST_F(MetricsAdaptorTest, InitializedFalseRejectsMetricAndEventTest)
{
    auto metricsAdaptor = std::make_shared<MetricsAdaptor>();
    metricsAdaptor->userEnable_ = true;
    metricsAdaptor->metricSampleEnabledInstruments_ = { "yr_custom_concurrent_num" };

    YR::Libruntime::GaugeData metricGauge;
    metricGauge.name = "yr_custom_concurrent_num";
    metricGauge.value = 1;
    ASSERT_EQ(metricsAdaptor->SetGauge(metricGauge).Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);
    ASSERT_TRUE(metricsAdaptor->doubleGaugeSamples_.empty());

    YR::Libruntime::GaugeData eventGauge;
    eventGauge.name = "call_metric";
    eventGauge.instrumentKind = YR::Libruntime::InstrumentKind::EVENT;
    eventGauge.value = 1;
    ASSERT_EQ(metricsAdaptor->ReportMetrics(eventGauge).Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);
    ASSERT_TRUE(metricsAdaptor->doubleGaugeSamples_.empty());
}

TEST_F(MetricsAdaptorTest, SameNameDifferentInstrumentKindReturnsErrorTest)
{
    Config::c = Config();
    auto metricsAdaptor = BuildMockInitializedMetricsAdaptor();

    YR::Libruntime::GaugeData eventGauge;
    eventGauge.name = "mixed_kind";
    eventGauge.instrumentKind = YR::Libruntime::InstrumentKind::EVENT;
    eventGauge.value = 1;
    ASSERT_EQ(metricsAdaptor->ReportMetrics(eventGauge).Code(), YR::Libruntime::ErrorCode::ERR_OK);

    YR::Libruntime::GaugeData metricGauge;
    metricGauge.name = "mixed_kind";
    metricGauge.value = 2;
    metricsAdaptor->metricSampleEnabledInstruments_.insert(metricGauge.name);
    ASSERT_EQ(metricsAdaptor->SetGauge(metricGauge).Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);
    ASSERT_TRUE(metricsAdaptor->doubleGaugeSamples_.empty());
}

TEST_F(MetricsAdaptorTest, contextTest)
{
    MetricsContext metricsContext;
    std::string attr = "test_attr";
    std::string value = "test_value";
    metricsContext.SetAttr(attr, value);
    std::string result = metricsContext.GetAttr(attr);
    ASSERT_EQ(result, value);

    attr = "test_attr_key";
    result = metricsContext.GetAttr(attr);
    ASSERT_EQ(result, "");
}

TEST_F(MetricsAdaptorTest, CanonicalizeLabelsInjectsPlatformLabels)
{
    ScopedPlatformEnv env;

    auto metricsAdaptor = std::make_shared<MetricsAdaptor>();
    std::unordered_map<std::string, std::string> labels = {{"biz", "value"}};
    auto canonicalized = metricsAdaptor->CanonicalizeLabels(labels);

    ASSERT_EQ(canonicalized["pod"], "runtime-pod");
    ASSERT_EQ(canonicalized["namespace"], "runtime-namespace");
    ASSERT_EQ(canonicalized["biz"], "value");
}

TEST_F(MetricsAdaptorTest, BuildPointLabelsInjectsPlatformLabels)
{
    ScopedPlatformEnv env;

    auto metricsAdaptor = std::make_shared<MetricsAdaptor>();
    std::unordered_map<std::string, std::string> labels = {{"biz", "value"}};

    const auto pointLabels = metricsAdaptor->BuildPointLabels(labels);

    EXPECT_THAT(pointLabels, Contains(std::pair<std::string, std::string>("pod", "runtime-pod")));
    EXPECT_THAT(pointLabels, Contains(std::pair<std::string, std::string>("namespace", "runtime-namespace")));
    EXPECT_THAT(pointLabels, Contains(std::pair<std::string, std::string>("biz", "value")));
}

TEST_F(MetricsAdaptorTest, InitHttpExporterWithTLS)
{
    auto metricsAdaptor = std::make_shared<MetricsAdaptor>();

    setenv("YR_SSL_ENABLE", "true", 1);
    setenv("YR_SSL_ROOT_FILE", "root", 1);
    setenv("YR_SSL_CERT_FILE", "cert", 1);
    setenv("YR_SSL_KEY_FILE", "key", 1);
    setenv("YR_SSL_PASSPHRASE", "123", 1);

    YR::Libruntime::Config::c = YR::Libruntime::Config();

    auto config = GetPrometheusPushExporterConfig();
    // Exporter may be null if SSL cert files are invalid; the key behavior under test is passphrase erasure.
    metricsAdaptor->InitHttpExporter("prometheusPushExporter", "key", "name", config);
    // Cleared via setenv(..., ""); on some platforms (e.g. Darwin) that removes the var, so getenv is nullptr.
    auto value = std::getenv("YR_SSL_PASSPHRASE");
    EXPECT_TRUE(value == nullptr || value[0] == '\0');

    unsetenv("YR_SSL_ENABLE");
    unsetenv("YR_SSL_ROOT_FILE");
    unsetenv("YR_SSL_CERT_FILE");
    unsetenv("YR_SSL_KEY_FILE");
    unsetenv("YR_SSL_PASSPHRASE");
    YR::Libruntime::Config::c = YR::Libruntime::Config();
}

TEST_F(MetricsAdaptorTest, BuildExportConfigsTest)
{
    auto metricsAdaptor = std::make_shared<MetricsAdaptor>();
    auto js = GetExportConfigs();
    ASSERT_TRUE(js.contains("enabledInstruments"));
    auto config = metricsAdaptor->BuildExportConfigs(GetExportConfigs());
    ASSERT_TRUE(config.enabledInstruments.count("name") > 0);
}

TEST_F(MetricsAdaptorTest, DisabledPrometheusPullExporterSslConfigSchemaTest)
{
    auto config = GetPrometheusPullExporterSslConfig();
    ASSERT_TRUE(config.contains("backends"));
    const auto &exporter =
        config.at("backends").at(0).at("immediatelyExport").at("exporters").at(0).at("prometheusPullExporter");
    ASSERT_FALSE(exporter.at("enable").get<bool>());
    ASSERT_TRUE(exporter.at("enabledInstruments").is_array());
    const auto &initConfig = exporter.at("initConfig");
    ASSERT_EQ(initConfig.at("ip").get<std::string>(), "127.0.0.1");
    ASSERT_EQ(initConfig.at("port").get<uint16_t>(), DISABLED_PROMETHEUS_PULL_EXPORTER_PORT);
    ASSERT_EQ(initConfig.at("metricsPath").get<std::string>(), "/metrics");
    ASSERT_TRUE(initConfig.at("isSSLEnable").get<bool>());
    ASSERT_TRUE(initConfig.at("mutualTlsEnable").get<bool>());
    ASSERT_EQ(initConfig.at("rootCertFile").get<std::string>(), "/tmp/root.crt");
    ASSERT_EQ(initConfig.at("certFile").get<std::string>(), "/tmp/server.crt");
    ASSERT_EQ(initConfig.at("keyFile").get<std::string>(), "/tmp/server.key");
    ASSERT_EQ(initConfig.at("passphrase").get<std::string>(), "secret");
}

TEST_F(MetricsAdaptorTest, GaugeDescriptionOverrideRecreatesInstrumentTest)
{
    Config::c = Config();
    auto metricsAdaptor = BuildMockInitializedMetricsAdaptor();

    YR::Libruntime::GaugeData defaultGauge;
    defaultGauge.name = "yr_custom_concurrent_num";
    defaultGauge.description = "default runtime concurrent number";
    defaultGauge.unit = "count";
    defaultGauge.value = 1;
    ASSERT_EQ(metricsAdaptor->SetGauge(defaultGauge).Code(), YR::Libruntime::ErrorCode::ERR_OK);
    ASSERT_TRUE(metricsAdaptor->doubleGaugeMap_.count(defaultGauge.name) > 0);

    YR::Libruntime::GaugeData overrideGauge = defaultGauge;
    overrideGauge.description = "override concurrent";
    overrideGauge.value = 9;
    ASSERT_EQ(metricsAdaptor->SetGauge(overrideGauge).Code(), YR::Libruntime::ErrorCode::ERR_OK);
    auto sampleKey =
        metricsAdaptor->BuildMetricSampleKey(overrideGauge.name,
                                             metricsAdaptor->CanonicalizeLabels(overrideGauge.labels));
    ASSERT_EQ(metricsAdaptor->doubleGaugeSamples_.at(sampleKey).description, "override concurrent");
    ASSERT_TRUE(metricsAdaptor->doubleGaugeMap_.count(overrideGauge.name) > 0);
    ASSERT_EQ(metricsAdaptor->doubleGaugeSamples_.at(sampleKey).description, "override concurrent");
    auto gaugeValue = metricsAdaptor->GetValueGauge(overrideGauge);
    ASSERT_TRUE(gaugeValue.first.OK());
    ASSERT_EQ(gaugeValue.second, 9);

    metricsAdaptor->CleanMetrics();
    EXPECT_EQ(MetricsApi::Provider::GetMeterProvider(), nullptr);
}

TEST_F(MetricsAdaptorTest, MetricSampleWhitelistControlsCachedOperationsTest)
{
    Config::c = Config();
    auto metricsAdaptor = BuildSampleOnlyMetricsAdaptor();
    YR::Libruntime::GaugeData gauge;
    gauge.name = "yr_custom_concurrent_num";
    gauge.description = "custom concurrent";
    gauge.unit = "count";
    gauge.value = 5;
    ASSERT_EQ(metricsAdaptor->SetGauge(gauge).Code(), YR::Libruntime::ErrorCode::ERR_OK);
    auto gaugeValue = metricsAdaptor->GetValueGauge(gauge);
    ASSERT_TRUE(gaugeValue.first.OK());
    ASSERT_EQ(gaugeValue.second, 5);

    YR::Libruntime::UInt64CounterData allowedCounter;
    allowedCounter.name = "yr_custom_invoke_num";
    allowedCounter.description = "custom invoke";
    allowedCounter.unit = "count";
    allowedCounter.value = 3;
    ASSERT_EQ(metricsAdaptor->IncreaseUInt64Counter(allowedCounter).Code(), YR::Libruntime::ErrorCode::ERR_OK);
    auto allowedValue = metricsAdaptor->GetValueUInt64Counter(allowedCounter);
    ASSERT_TRUE(allowedValue.first.OK());
    ASSERT_EQ(allowedValue.second, 3);

    YR::Libruntime::UInt64CounterData blockedCounter;
    blockedCounter.name = "yr_custom_blocked_num";
    blockedCounter.description = "blocked";
    blockedCounter.unit = "count";
    blockedCounter.value = 7;
    ASSERT_EQ(metricsAdaptor->IncreaseUInt64Counter(blockedCounter).Code(),
              YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);
    auto blockedValue = metricsAdaptor->GetValueUInt64Counter(blockedCounter);
    ASSERT_EQ(blockedValue.first.Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);
    ASSERT_EQ(blockedValue.second, 0);
}

TEST_F(MetricsAdaptorTest, ReportMetricsOnlyCachesMetricSampleEnabledInstrumentsTest)
{
    Config::c = Config();
    auto metricsAdaptor = BuildMockInitializedMetricsAdaptor();

    YR::Libruntime::GaugeData callMetric;
    callMetric.name = "call_metric";
    callMetric.instrumentKind = YR::Libruntime::InstrumentKind::EVENT;
    callMetric.labels["requestid"] = "request-1";
    callMetric.labels["traceid"] = "trace-1";
    callMetric.value = 1;
    ASSERT_EQ(metricsAdaptor->ReportMetrics(callMetric).Code(), YR::Libruntime::ErrorCode::ERR_OK);
    ASSERT_TRUE(metricsAdaptor->doubleGaugeSamples_.empty());

    YR::Libruntime::GaugeData enabledMetric;
    enabledMetric.name = "yr_custom_concurrent_num";
    enabledMetric.description = "custom concurrent";
    enabledMetric.unit = "count";
    enabledMetric.value = 5;
    ASSERT_EQ(metricsAdaptor->ReportMetrics(enabledMetric).Code(), YR::Libruntime::ErrorCode::ERR_OK);
    ASSERT_EQ(metricsAdaptor->doubleGaugeSamples_.size(), 1);

    metricsAdaptor->CleanMetrics();
    EXPECT_EQ(MetricsApi::Provider::GetMeterProvider(), nullptr);
}

TEST_F(MetricsAdaptorTest, EventInstrumentIsNotBlockedByMetricSampleWhitelistTest)
{
    Config::c = Config();
    auto metricsAdaptor = BuildMockInitializedMetricsAdaptor();

    YR::Libruntime::GaugeData sampleMetric;
    sampleMetric.name = "yr_custom_concurrent_num";
    sampleMetric.description = "custom concurrent";
    sampleMetric.unit = "count";
    sampleMetric.value = 5;
    ASSERT_EQ(metricsAdaptor->SetGauge(sampleMetric).Code(), YR::Libruntime::ErrorCode::ERR_OK);
    ASSERT_EQ(metricsAdaptor->doubleGaugeSamples_.size(), 1);

    YR::Libruntime::GaugeData eventMetric;
    eventMetric.name = "push_only_metric";
    eventMetric.description = "push only";
    eventMetric.unit = "count";
    eventMetric.instrumentKind = YR::Libruntime::InstrumentKind::EVENT;
    eventMetric.value = 9;
    ASSERT_EQ(metricsAdaptor->SetGauge(eventMetric).Code(), YR::Libruntime::ErrorCode::ERR_OK);
    ASSERT_EQ(metricsAdaptor->doubleGaugeSamples_.size(), 1);
    auto eventValue = metricsAdaptor->GetValueGauge(eventMetric);
    ASSERT_EQ(eventValue.first.Code(), YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);

    YR::Libruntime::GaugeData metricNotWhitelisted;
    metricNotWhitelisted.name = "metric_not_whitelisted";
    metricNotWhitelisted.description = "metric not whitelisted";
    metricNotWhitelisted.unit = "count";
    metricNotWhitelisted.value = 10;
    ASSERT_EQ(metricsAdaptor->SetGauge(metricNotWhitelisted).Code(),
              YR::Libruntime::ErrorCode::ERR_INNER_SYSTEM_ERROR);
    ASSERT_EQ(metricsAdaptor->doubleGaugeSamples_.size(), 1);

    metricsAdaptor->CleanMetrics();
    EXPECT_EQ(MetricsApi::Provider::GetMeterProvider(), nullptr);
}

}  // namespace test
}  // namespace YR
