# Traefik HTTP Provider

AIO 中 Traefik 的静态 file provider 只维护 frontend 和 `/direct` 路由；实例级 tunnel 和用户端口路由由 FunctionMaster 提供。

- Provider endpoint: `http://<AIO_NODE_IP>:22770/global-scheduler/traefik/config`
- Poll interval / timeout: `5s` / `5s`
- `direct` 端口只保留在 SandboxRouter，不进入 Traefik 动态配置。
- `tunnel` 发布为 `/tunnel/{safeID}`。
- `http`/`https` public 端口发布为 `/{safeID}/{containerPort}`。

FunctionMaster standby 会把 provider 查询转发到 leader；临时 503 时 Traefik 保留上一份有效配置。
