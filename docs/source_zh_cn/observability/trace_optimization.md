# Trace 全链路优化说明

本文说明本次 openYuanrong Trace 优化的设计、部署方式和使用方法，重点覆盖 FaaS 场景下 `frontend -> scheduler -> function_proxy -> runtime` 的链路关联。

## 背景

优化前，FaaS 请求虽然可以透传业务侧的 `X-Trace-Id`，但不同组件内部创建 Span 的方式并不一致，主要有以下问题：

- `X-Trace-Id` 可以用于日志关联，但不能稳定形成统一的 OTel 父子链路。
- `frontend`、`scheduler`、`function_proxy` 在冷启动 `create` 路径上容易拆成多条独立 Trace。
- 部分组件上报到后端时 `service.name` 不明确，不利于在 Grafana / Tempo 中按服务检索。
- Trace 开关和 exporter 配置分散，部署和排查成本较高。

## 优化目标

本次优化目标如下：

- 普通 UUID 格式的 `X-Trace-Id` 可以稳定映射为 OTel `trace_id`。
- `frontend` 作为入口创建根 Span，并向下游传播标准 `traceparent`。
- `scheduler`、`function_proxy`、`runtime` 优先基于 `traceparent` 建立父子关系，而不是仅依赖裸 `traceID`。
- functionsystem 相关组件以组件名作为 `service.name` 上报。
- Trace 开关和 exporter 配置统一通过 `yr start` 注入。

## 方案概览

### 1. 入口统一

HTTP 入口收到请求后：

- 保留原始 `X-Trace-Id` 作为用户侧关联 ID。
- 当请求头中存在合法 `Traceparent` 时，直接沿用上游上下文。
- 当请求头中不存在 `Traceparent`，但存在合法 `X-Trace-Id` 时，使用该值生成 OTel `trace_id`，并在 `frontend` 创建新的根 Span。
- `frontend` 将新的子上下文重新注入到请求头中的 `Traceparent`，供后续内部调用继续透传。

这样可以同时满足两个需求：

- 用户仍然可以使用 `X-Trace-Id` 检索业务请求。
- 系统内部使用标准 `traceparent` 维持父子 Span 关系。

### 2. Raw 接口透传 `traceparent`

FaaS 场景中，`frontend` 和 `scheduler` 通过 raw 接口调用底层 libruntime。为避免在链路中间丢失父 Span，上下游透传采用以下规则：

- `frontend` 调用 raw create / invoke / kill 接口时，显式传入 `RawRequestOption.TraceParent`。
- Go libruntime SDK 将 `TraceParent` 继续传给 C++ libruntime。
- C++ libruntime 在反序列化 raw 请求后，将 `traceparent` 写入：
  - `createoptions["traceparent"]`
  - `schedulingops.extension["traceparent"]`
  - `invokeoptions.customtag["traceparent"]`

这样做的目的，是让 functionsystem 在真正处理 proto 请求时能够从标准扩展字段中恢复父 Span。

### 3. 冷启动 create 路径补齐

冷启动场景下，真实链路为：

```text
frontend root span
  -> frontend CreateHandler / invoke handler
  -> scheduler yr.create
  -> function_proxy yr.create
  -> function_proxy yr.schedule.local
  -> function_proxy yr.instance.deploy
  -> function_proxy yr.instance.wait_connection
  -> runtime invoke
```

为了把这条链路串起来，本次优化做了两件事：

- `scheduler` 保留冷启动请求的 `traceID + traceparent`，在真正触发 create 时继续向下传递。
- functionsystem 的 `Create` / `Schedule` 路径优先从 `traceparent` 恢复父上下文，并继续把当前 Span 的 `traceparent` 写回 options，供后续子流程使用。

### 4. service.name 规范化

functionsystem 侧原先可能以统一的内核名上报，Grafana 中不利于定位真实组件。本次优化后，相关组件以自身组件名作为 `service.name` 上报，例如：

- `function_proxy`
- `function_master`
- `faas-frontend`
- `driver-scheduler-<node-id>`

### 5. Trace 配置统一

Trace 开关和 exporter 配置统一通过以下启动参数控制：

- `--enable_trace`
- `--trace_config`
- `--runtime_trace_config`

其中：

- `trace_config` 用于函数系统组件。
- `runtime_trace_config` 用于 runtime / driver runtime。

推荐两者保持一致。

## 部署方式

### 前置条件

需要准备可用的 OTLP gRPC 接收端，例如：

- otel-collector
- Tempo
- Jaeger

默认 OTLP gRPC 端口一般为 `4317`。

### 推荐部署方式

使用开启 Trace 的参数启动集群：

```bash
yr start --master -a <HOST_IP> \
  --enable_trace true \
  --trace_config '{"otlpGrpcExporter":{"enable":true,"endpoint":"<OTLP_HOST>:4317"},"logFileExporter":{"enable":true}}' \
  --runtime_trace_config '{"otlpGrpcExporter":{"enable":true,"endpoint":"<OTLP_HOST>:4317"},"logFileExporter":{"enable":true}}'
```

如果本机默认 `8889` 已被占用，启动 FaaS scheduler 时可以显式指定 lease 端口：

```bash
yr start --master -a <HOST_IP> \
  --enable_faas_frontend true \
  --enable_function_scheduler true \
  --function_scheduler_lease_port 18889 \
  --enable_trace true \
  --trace_config '{"otlpGrpcExporter":{"enable":true,"endpoint":"<OTLP_HOST>:4317"},"logFileExporter":{"enable":true}}' \
  --runtime_trace_config '{"otlpGrpcExporter":{"enable":true,"endpoint":"<OTLP_HOST>:4317"},"logFileExporter":{"enable":true}}'
```

### 调试场景下仅替换 `faasscheduler.so`

如果只需要快速验证 scheduler 侧修复，可以直接用新产物覆盖安装件：

```bash
cp /home/robbluo/code/yuanrong/build/_output/faasscheduler/faasscheduler.so \
  /opt/buildtools/python3.11/lib/python3.11/site-packages/yr/inner/pattern/pattern_faas/faasscheduler/faasscheduler.so
```

替换后必须重启集群，运行中的 `scheduler_libruntime` 不会热加载新的 `.so`。

## 使用方式

### 1. 业务请求侧

业务侧可以继续传递：

- `X-Trace-Id`
- `Traceparent`，如果业务上游本身已经接入 OTel

推荐做法：

- 集群外调用方如果没有 OTel，只传 `X-Trace-Id` 即可。
- 集群外调用方如果已经有 OTel，优先同时传 `Traceparent`，这样可以保留真实的跨系统父子关系。

### 2. FaaS 验证示例

部署 runtime：

```bash
yrcli --server-address <FRONTEND_ADDR> \
  --ds-address <DS_ADDR> \
  --client-auth-type one-way \
  --user default \
  deploy-language-rt --runtime python3.11 --sdk --no-rootfs
```

部署函数：

```bash
yrcli --server-address <FRONTEND_ADDR> \
  --client-auth-type one-way \
  --user default \
  deploy --skip-package true --function-json <FUNCTION_JSON>
```

调用函数：

```bash
yrcli --server-address <FRONTEND_ADDR> \
  --client-auth-type one-way \
  --user default \
  invoke -f faaspy@tracecheck \
  --payload '{"name":"trace"}' \
  --header X-Trace-Id:6a4b9c2d-1357-4a8e-9bcd-2468ace02468
```

### 3. 在 Grafana / Tempo 中查看

如果已经启用 OTLP exporter，可以在 Grafana Explore 中按 Trace ID 或 Service Name 查询。

典型服务名包括：

- `faas-frontend`
- `driver-scheduler-<node-id>`
- `function_proxy`

如果业务使用的是 UUID 格式的 `X-Trace-Id`，需要在后端按去掉连字符后的 32 位十六进制 Trace ID 检索，例如：

```text
6a4b9c2d-1357-4a8e-9bcd-2468ace02468
-> 6a4b9c2d13574a8e9bcd2468ace02468
```

### 4. 在日志中查看

如果同时启用了 `logFileExporter`，可直接在日志中搜索：

- 原始业务 Trace ID，例如 `6a4b9c2d-1357-4a8e-9bcd-2468ace02468`
- 或关键字 `trace info`

主机部署常见目录：

- `/tmp/yr_sessions/latest/log`

可重点关注：

- `faasfrontend.so-run.*.log`
- `faasscheduler.so-run.*.log`
- `*function_proxy.log`
- `*scheduler_libruntime.log`
- `job-*-runtime-*.log`

## 验证结果

本次优化完成后，已验证以下行为：

- `frontend`、`scheduler`、`function_proxy`、`runtime` 可以共享同一业务 Trace ID。
- 冷启动 `create` 路径不再拆成多条独立 Trace。
- `scheduler` 的 `yr.create` 和 `function_proxy` 的 `yr.create` / `yr.schedule.local` / `yr.instance.deploy` / `yr.instance.wait_connection` 可以关联到同一条 Trace。
- 开启 exporter 后，可以在 Tempo / Grafana 中查询到导出的 Trace 数据。

## 排查建议

如果发现链路没有串起来，优先检查以下内容：

1. 请求头中是否存在 `X-Trace-Id` 或 `Traceparent`。
2. `frontend` 是否已经开启 Trace，并在入口重新注入 `Traceparent`。
3. `trace_config` 和 `runtime_trace_config` 是否同时开启。
4. `scheduler_libruntime` 和 `faasscheduler.so` 是否使用了最新产物。
5. 是否重启过集群。
6. OTLP endpoint 是否可达，Exporter 是否正常工作。

## 注意事项

- `X-Trace-Id` 主要用于业务关联和生成稳定的 OTel Trace ID。
- 真正用于构建跨组件父子关系的是 `Traceparent`。
- 仅传 `traceID`、不传 `traceparent` 时，不保证所有组件都能形成严格的父子 Span 关系。
- 调试时如果只替换 `.so`，必须确认对应 driver runtime 已经重启，否则仍会沿用旧进程中的旧逻辑。
