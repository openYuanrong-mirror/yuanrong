# 可观测性

## 概述

集成 OpenTelemetry、Prometheus、Loki、Tempo 实现完整的可观测性方案。

## OpenTelemetry

### 架构

    应用 → OTel SDK → OTel Collector → Backend
                              │
                  ┌───────────┼───────────┐
                  ▼           ▼           ▼
               Jaeger      Prometheus   Loki/Tempo

### 配置参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | string | OTLP 接收端地址 |
| `OTEL_SERVICE_NAME` | string | 服务名称 |
| `OTEL_TRACES_EXPORTER` | string | traces 导出器 (otlp, jaeger, zipkin) |
| `OTEL_METRICS_EXPORTER` | string | metrics 导出器 |

### Trace 接口

#### Span 属性

标准 span 属性：

| 属性 | 说明 |
|------|------|
| `service.name` | 服务名称 |
| `service.version` | 服务版本 |
| `span.kind` | span 类型 (server, client, producer, consumer) |
| `tenant.id` | 租户 ID |

#### 自定义 Span

```python
import yr
from yr import trace

config = yr.Config(enable_trace=True)
yr.init(config)

# 获取 tracer
tracer = trace.get_tracer(__name__)

# 使用 context manager
with tracer.start_as_current_span("my_operation") as span:
    span.set_attribute("custom.key", "value")
    # 执行操作

# 使用装饰器
@trace.in_context_span("process_data")
def process_data(data):
    return data * 2
```

### Metrics 接口

#### 指标类型

| 类型 | 说明 | 使用场景 |
|------|------|----------|
| UInt64Counter | 64位无符号整数计数器 | 请求次数、错误计数 |
| DoubleCounter | 双精度浮点计数器 | 精确计数 |
| Histogram | 直方图 | 延迟分布、响应大小 |
| Gauge | 瞬时值 | CPU 使用率、连接数 |
| Alarm | 告警 | 异常告警 |

#### Python SDK

```python
import yr

config = yr.Config(enable_metrics=True)
yr.init(config)

# UInt64Counter
counter = yr.UInt64Counter("requests_total", "Total requests", "count")
counter.increase(1)

# DoubleCounter
double_counter = yr.DoubleCounter("bytes_total", "Total bytes", "bytes")
double_counter.increase(1024.5)

# Histogram
histogram = yr.Histogram("request_latency_ms", "Request latency", "ms")
histogram.record(123.45)

# Gauge
gauge = yr.Gauge("cpu_usage_percent", "CPU usage", "percent")
gauge.set(45.2)

# Alarm
alarm = yr.Alarm("high_error_rate", "Error rate too high")
alarm_info = yr.AlarmInfo(alarm_name="error_spike", severity=yr.AlarmSeverity.WARNING)
alarm.set(alarm_info)
```

## Prometheus

### 集成方式

支持两种模式：

1. **Pull 模式**：Prometheus Server 主动拉取
2. **Push 模式**：应用主动推送

### Push Gateway

```yaml
metrics:
  push_gateway:
    enabled: true
    endpoint: "http://prometheus-pushgateway:9091"
    job_name: "yuanrong-functions"
    interval: 10s
```

### 指标端点

| 端点 | 说明 |
|------|------|
| `/metrics` | Prometheus 格式指标 |
| `/metrics/json` | JSON 格式指标 |

### 内置指标

| 指标名称 | 类型 | 说明 |
|----------|------|------|
| `yr_function_invokes_total` | Counter | 函数调用总数 |
| `yr_function_latency_seconds` | Histogram | 函数调用延迟 |
| `yr_instance_count` | Gauge | 运行实例数 |
| `yr_instance_memory_bytes` | Gauge | 实例内存使用 |
| `yr_scheduler_queue_size` | Gauge | 调度队列大小 |

## Loki (日志)

### 配置

```yaml
logs:
  loki:
    enabled: true
    endpoint: "http://loki:3100/loki/api/v1/push"
    labels:
      app: "yuanrong"
      component: "function-system"
```

### 日志格式

结构化 JSON 日志：

```json
{
  "timestamp": "2026-03-25T10:00:00.000Z",
  "level": "INFO",
  "service": "function-proxy",
  "trace_id": "abc123",
  "span_id": "def456",
  "message": "Function invoked",
  "function_name": "my-func",
  "tenant_id": "tenant-abc"
}
```

### UTC 时间配置

```yaml
logs:
  use_utc_time: true
```

## Tempo (链路追踪)

### 配置

```yaml
traces:
  tempo:
    enabled: true
    endpoint: "http://tempo:3200"
    protocol: "grpc"  # 或 "http"
```

### 关联日志和链路

通过 `trace_id` 和 `span_id` 关联：

    Trace ID: abc123 ─────────────────────────────────────────▶
        │
        ├── Span: foo (abc123.1) ──▶ Log: "foo started"
        │                                Log: "foo completed"
        │
        └── Span: bar (abc123.2) ──▶ Log: "bar processing"

## Grafana 集成

### Dashboard

提供完整的监控 Dashboard，包含：

- 函数调用统计
- 延迟分布
- 实例资源使用
- 调度队列状态
- 错误率监控

### 告警规则

```yaml
groups:
  - name: yuanrong-alerts
    rules:
      - alert: HighErrorRate
        expr: rate(yr_function_errors_total[5m]) > 0.1
        for: 5m
        labels:
          severity: critical
```

## 监控端点汇总

| 端点 | 格式 | 说明 |
|------|------|------|
| `/metrics` | Prometheus | 指标数据 |
| `/health` | JSON | 健康检查 |
| `/health/ready` | JSON | 就绪检查 |
| `/health/live` | JSON | 存活检查 |
| `/trace/zipkin` | Zipkin | Zipkin 格式链路 |
