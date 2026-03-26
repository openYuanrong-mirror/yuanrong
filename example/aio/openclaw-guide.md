# OpenClaw 说明

`example/aio` 当前版本不再内置 `openclaw`。

这次重构的目标是：

- 将 `aio-yr` 主镜像与 runtime 镜像拆分
- 在主容器内运行真实 Docker in Docker
- 保留 web terminal、Traefik 和 Yuanrong master
- 优先缩小镜像职责和体积

因此，`openclaw` 和 `claude-code` 暂时不打入镜像。后续如果需要恢复这类 Agent 工具，应作为可选扩展层处理，而不是直接塞进基础 AIO 镜像。
