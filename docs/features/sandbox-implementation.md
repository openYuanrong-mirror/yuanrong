# Sandbox 实现综述

## 概述

`api/python/yr/sandbox/sandbox.py` 不是一个独立的 sandbox runtime，而是
`yr` Python SDK 对“实例创建、远端命令执行、端口暴露、reverse tunnel”的高层封装。

它横跨三个仓库：

- `yuanrong`
  - 提供 `yr` Python SDK
  - 提供 `SandBox` 封装、`TunnelClient`、`TunnelServer`
- `functionsystem`
  - 负责实例创建、runtime 环境变量注入、端口映射、Traefik 注册
- `frontend`
  - 提供 WebTerminal 和浏览器侧 sandbox 创建入口
  - 通过 job 提交链路间接调用 `yr` CLI 和 sandbox 能力

## 组件边界

### yuanrong: SDK 侧职责

`sandbox.py` 的主要职责：

- 构造 `yr.InvokeOptions`
- 基于 `@yr.instance` 创建远端 Python 实例
- 对外暴露 `exec()`、`cleanup()`、`terminate()` 等简化接口
- 在启用 `upstream` 时，补上 reverse tunnel 的本地 client 和远端 server

关键入口：

- `create()`:
  [sandbox.py](/home/wyc/code/sandbox/api/python/yr/sandbox/sandbox.py#L252)
- `SandBox.__init__()`:
  [sandbox.py](/home/wyc/code/sandbox/api/python/yr/sandbox/sandbox.py#L304)
- `SandboxInstance.execute()`:
  [sandbox.py](/home/wyc/code/sandbox/api/python/yr/sandbox/sandbox.py#L128)

### functionsystem: 控制面职责

`functionsystem` 负责把 SDK 侧的实例创建请求变成真实运行实例，核心包括：

- 解析 `createOptions`
- 写入 `InstanceInfo`
- 给 runtime 注入 `YR_SERVER_ADDRESS`、`YR_DS_ADDRESS`、`INSTANCE_ID`
- 为请求的 sandbox 端口分配 host port
- 把实例注册到 Traefik，生成 `/{safeID}/{sandboxPort}` 路径路由

关键实现：

- detached lifecycle 下沉：
  [struct_transfer.h](/home/wyc/code/sandbox/functionsystem/functionsystem/src/common/utils/struct_transfer.h#L880)
- runtime 环境变量注入：
  [build.cpp](/home/wyc/code/sandbox/functionsystem/functionsystem/src/runtime_manager/config/build.cpp#L181)
- runtime launcher 端口字段：
  [runtime_launcher.proto](/home/wyc/code/sandbox/functionsystem/runtime-launcher/api/proto/runtime/v1/runtime_launcher.proto#L88)
- host port 分配与 `protocol:hostPort:containerPort` 编码：
  [container_executor.cpp](/home/wyc/code/sandbox/functionsystem/functionsystem/src/runtime_manager/executor/container_executor.cpp#L770)
- Traefik 注册：
  [instance_ctrl_actor.cpp](/home/wyc/code/sandbox/functionsystem/functionsystem/src/function_proxy/local_scheduler/instance_control/instance_ctrl_actor.cpp#L6609)
  [traefik_registry.cpp](/home/wyc/code/sandbox/functionsystem/functionsystem/src/function_proxy/local_scheduler/traefik_registry/traefik_registry.cpp#L70)

### frontend: 浏览器入口职责

`frontend` 不直接 import `sandbox.py`，但会在浏览器侧创建 sandbox job。
它本质上是在准备运行环境，然后让远端执行 `yr` CLI。

关键实现：

- Web 页面构造 sandbox 创建请求：
  [webterm.go](/home/wyc/code/sandbox/frontend/pkg/frontend/webui/webterm.go#L1246)
- 其中显式注入：
  `YR_JWT_TOKEN`、`YR_SERVER_ADDRESS`、`YR_DS_ADDRESS`

## 创建链路

普通 sandbox 的创建流程如下：

```text
Python user
  -> yr.sandbox.create() / yr.sandbox.SandBox()
  -> SandBox.__init__()
  -> yr.InvokeOptions(skip_serialize=True)
  -> SandboxInstance.options(opt).invoke(...)
  -> yr runtime / libruntime
  -> functionsystem create instance
  -> runtime 启动预部署的 Python SDK 类
```

这里有两个关键点。

第一，`SandboxInstance` 是一个被 `@yr.instance` 装饰的 Python 类，不是本地对象。
它的方法调用最终会被转成远端实例调用。

第二，`skip_serialize=True` 意味着 SDK 不再序列化整个类定义上传，而是假设远端环境已经有
同路径的预部署类。这个逻辑在
[instance_proxy.py](/home/wyc/code/sandbox/api/python/yr/decorator/instance_proxy.py#L232)
里实现。

## 命令执行模型

创建出来的 `SandBox` 对象，实际对外暴露的是远端实例代理：

- `exec()` 调用远端 `SandboxInstance.execute()`
- `get_working_dir()` 调用远端 `SandboxInstance.get_working_dir()`
- `cleanup()` 调用远端 `SandboxInstance.cleanup()`
- `terminate()` 先停 tunnel client，再终止实例

`execute()` 的实际执行方式很直接：

- 在远端 runtime 内使用 `subprocess.run(...)`
- `cwd` 使用 sandbox working dir
- `env` 使用实例环境变量

实现位置：
[sandbox.py](/home/wyc/code/sandbox/api/python/yr/sandbox/sandbox.py#L155)

## detached 模式

CLI 和 frontend 创建 sandbox 时，常用 detached 生命周期。

Python SDK 侧约定：

- `InvokeOptions.custom_extensions["lifecycle"] = "detached"`

相关位置：

- `sandbox.py` CLI 入口：
  [sandbox.py](/home/wyc/code/sandbox/api/python/yr/sandbox/sandbox.py#L404)
- `instance_proxy.py` 参数校验：
  [instance_proxy.py](/home/wyc/code/sandbox/api/python/yr/decorator/instance_proxy.py#L317)
- `InvokeOptions` 文档：
  [config.py](/home/wyc/code/sandbox/api/python/yr/config.py#L411)

后端接收后，会在 `InstanceInfo` 上标记 `detached`，从而使实例生命周期脱离创建它的父调用链。

## 端口转发实现

`sandbox.py` 里对外暴露的 gateway URL 和 reverse tunnel，本质都依赖现有的端口转发能力。

SDK 侧流程：

1. 用户设置 `InvokeOptions.port_forwardings`
2. `yr.port_forwarding.parse_port_forwardings()` 把它编码到
   `createOptions["network"]`
3. libruntime 把 `createOptions` 发到 functionsystem

编码实现：
[port_forwarding.py](/home/wyc/code/sandbox/api/python/yr/port_forwarding.py#L43)

后端流程：

1. runtime manager 解析 network 配置
2. 为每个 sandbox port 申请 host port
3. 生成 `protocol:hostPort:containerPort`
4. instance control 将它转换成 Traefik `PortMapping`
5. `TraefikRegistry` 生成 `/{safeID}/{sandboxPort}` 路由

因此，Python 侧自己也必须严格复用同样的实例 ID 清洗逻辑和 URL 格式：

- `_sanitize_instance_id()`:
  [sandbox.py](/home/wyc/code/sandbox/api/python/yr/sandbox/sandbox.py#L32)
- `_build_gateway_url()`:
  [sandbox.py](/home/wyc/code/sandbox/api/python/yr/sandbox/sandbox.py#L62)

这套实现与 `functionsystem` 的
`TraefikRegistry::SanitizeID` 和 `RegisterInstance` 保持一致：

- [traefik_registry.cpp](/home/wyc/code/sandbox/functionsystem/functionsystem/src/function_proxy/local_scheduler/traefik_registry/traefik_registry.cpp#L85)
- [traefik_registry.cpp](/home/wyc/code/sandbox/functionsystem/functionsystem/src/function_proxy/local_scheduler/traefik_registry/traefik_registry.cpp#L192)

## reverse tunnel 实现

当 `yr.sandbox.create(upstream=...)` 传入 `upstream` 时，
`sandbox.py` 会扩展普通 sandbox 创建链路。

### 端口模型

- Port A: `proxy_port - 1`
  - 注册到 Traefik
  - SDK 通过 WebSocket 连入
- Port B: `proxy_port`
  - 仅绑定 sandbox loopback
  - sandbox 内部 HTTP/WS 请求统一走这里

### 创建流程

```text
Host SDK
  -> create(upstream=127.0.0.1:19080)
  -> 给实例增加 tunnel port forwarding
  -> 创建远端 sandbox
  -> 在远端启动 TunnelServer
  -> 通过 Traefik URL 拼出 wss://.../{safeID}/{portA}
  -> 在宿主机启动 TunnelClient
  -> TunnelClient 连接 Port A
  -> sandbox 内部访问 http://127.0.0.1:{portB}
  -> TunnelServer / TunnelClient 转发到本地 upstream
```

关键实现：

- 启动远端 tunnel server：
  [sandbox.py](/home/wyc/code/sandbox/api/python/yr/sandbox/sandbox.py#L327)
- 启动本地 tunnel client：
  [sandbox.py](/home/wyc/code/sandbox/api/python/yr/sandbox/sandbox.py#L335)
- 返回 sandbox 内部代理 URL：
  [sandbox.py](/home/wyc/code/sandbox/api/python/yr/sandbox/sandbox.py#L358)

### gateway host 来源

构造 Traefik/gateway URL 时，host 优先级如下：

1. `YR_GATEWAY_ADDRESS`
2. `YR_SERVER_ADDRESS`
3. `ConfigManager().server_address`

实现位置：
[sandbox.py](/home/wyc/code/sandbox/api/python/yr/sandbox/sandbox.py#L51)

这保证了宿主 SDK 在 `in_cluster=False` 场景下，也能用初始化时的 server address
正确拼出 gateway URL。

## frontend 与 sandbox.py 的关系

frontend WebTerminal 页面里的 sandbox 创建，本质上是“让远端 runtime 执行
`yr.cli.scripts sandbox create`”，而不是直接在浏览器服务进程里构造 `SandBox` 对象。

但是两者复用同样的基础设施：

- 都依赖 `YR_SERVER_ADDRESS`
- 都依赖 `YR_DS_ADDRESS`
- 都依赖 functionsystem 创建 detached instance
- 都依赖 runtime 注入 `INSTANCE_ID`、proxy 地址、datasystem 地址

其中 `frontend` 在
[webterm.go](/home/wyc/code/sandbox/frontend/pkg/frontend/webui/webterm.go#L1262)
里构造 payload，把这些环境变量显式注入到远端运行环境；
而 `yr` SDK 在
[apis.py](/home/wyc/code/sandbox/api/python/yr/apis.py#L106)
里会从环境变量读取默认配置。

因此可以把 frontend 理解为 sandbox/yr CLI 的浏览器入口，而不是另一套独立 sandbox 实现。

## 关键环境变量

运行这条链路时，最关键的环境变量有：

| 变量 | 来源 | 作用 |
| ---- | ---- | ---- |
| `YR_SERVER_ADDRESS` | frontend 注入或 runtime 注入 | SDK 连接 proxy / gateway 的默认地址 |
| `YR_DS_ADDRESS` | frontend 注入或 runtime 注入 | datasystem 地址 |
| `INSTANCE_ID` | runtime 注入 | sandbox 内获取实例 ID |
| `YR_JWT_TOKEN` | frontend 注入 | 前端提交链路的用户认证 |

runtime 注入位置：
[build.cpp](/home/wyc/code/sandbox/functionsystem/functionsystem/src/runtime_manager/config/build.cpp#L181)

## 文档结论

`sandbox.py` 的准确定位是：

- 在 `yuanrong` 侧，它是一个基于 `yr.instance` 的高层 facade
- 在 `functionsystem` 侧，它依赖实例生命周期、runtime env、port forwarding、Traefik 路由
- 在 `frontend` 侧，它对应浏览器创建 sandbox 的上游入口

换句话说，`sandbox.py` 不是一套孤立功能，而是三仓库共同完成的一条端到端能力：

- `yuanrong` 负责 SDK 抽象和 tunnel 端点
- `functionsystem` 负责实例与网络控制面
- `frontend` 负责用户入口和运行时环境注入
