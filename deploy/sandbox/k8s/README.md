# yr-k8s

`deploy/sandbox/k8s` is the Kubernetes deployment surface for the split `yr` images and Helm chart tracked in `docs/features/2026-04-19-yr-k8s-design.md`.

This directory currently contains:

- layered image build scaffolding for `yr-base`, `yr-compile`, `yr-runtime`, `yr-controlplane`, and `yr-node`
- `yr start --block` entrypoint wrappers for `master`, `frontend`, and `node`
- a Helm chart for the three active workloads plus support objects; Frontend
  and Rust Edge are exposed directly and do not require an ingress process
- local and production values overlays

## Build inputs

Run `make all` from the repository root before invoking `deploy/sandbox/k8s/build-images.sh`.

The build script validates artifacts in the repository root `output/` directory, then builds local layered images. `yr-base` owns the shared Ubuntu/Python/runtime-library layer, `yr-compile` adds compile tools, `yr-controlplane` installs the control-plane wheels and entrypoints, `yr-node` adds node-only Docker/supervisor wiring, and `yr-runtime` installs only the SDK wheel needed by function containers. Master and frontend share `yr-controlplane`; their behavior is selected by the Helm command. Runtime function containers use `yr-runtime` through the generated `services.yaml`. It still fails fast when required artifacts are missing.

Required `output/` artifacts:

- `openyuanrong-*.whl`
- `openyuanrong_runtime-*.whl`
- `openyuanrong_faas-*.whl`
- `openyuanrong_dashboard-*.whl`
- `openyuanrong_cpp_sdk-*.whl`
- `openyuanrong_functionsystem-*.whl`
- `openyuanrong_datasystem-*.whl`
- `openyuanrong_sdk*.whl`

## Current workflow

1. Produce build artifacts:

```bash
make all
```

2. Build the local images:

```bash
bash deploy/sandbox/k8s/build-images.sh
```

3. Push the built images to SWR when needed:

```bash
bash deploy/sandbox/k8s/push-images-swr.sh
```

Buildkite pushes per-architecture image tags first, then `package_sandbox_manifest.sh` publishes the final multi-architecture manifest tag used by the Helm values.

4. Run the focused scaffold and chart tests:

```bash
python3 -m pytest deploy/sandbox/k8s/tests/test_yr_k8s_layout.py -q
```

5. Lint the Helm chart:

```bash
helm lint deploy/sandbox/k8s/charts/yr-k8s -f deploy/sandbox/k8s/k8s/values.local.yaml
```

6. Render the chart:

```bash
helm template yr-k8s deploy/sandbox/k8s/charts/yr-k8s
helm template yr-k8s deploy/sandbox/k8s/charts/yr-k8s -f deploy/sandbox/k8s/k8s/values.local.yaml
helm template yr-k8s deploy/sandbox/k8s/charts/yr-k8s -f deploy/sandbox/k8s/k8s/values.prod.yaml
```

7. Deploy to the target cluster when ready:

```bash
bash deploy/sandbox/k8s/deploy.sh
```

8. Run the off-cluster smoke checks:

```bash
YR_ENABLE_TLS=false bash test/st/run_off_cluster_test.sh -a <frontend-ip>:8888 -- -m smoke
```

## Values overlays

`deploy/sandbox/k8s/k8s/values.local.yaml`

- local image tags
- local registry override
- developer-oriented namespace and service exposure defaults

`deploy/sandbox/k8s/k8s/values.prod.yaml`

- stable image tags
- production registry override
- higher replica counts for control-plane workloads
- production storage and scale defaults

## Notes

- the active workload model is `master`, `frontend`, and `node`; when
  `dataPlane.enabled=true`, the frontend Pod also runs an independently
  supervised Rust Edge process and each node session starts the Rust Node
  Gateway as a separate `yr start` component
- `master` uses `yr start --master -e` and additionally enables scheduler, meta-service, and iam-server
- `frontend` uses `yr start -e --enable_faas_frontend true`
- `node` uses `yr start -e`
- `yr-runtime` is pushed as its own image and referenced by the `py39` runtime rootfs
- `etcd` is external in this model and is passed in through `global.externalEtcd`
- repeated CI deployments stop the existing runtime workloads, wait for their pods to exit, then reset the managed sandbox `etcd` state before installing fresh workloads. This prevents stale pod IPs, frontend drivers, and job leases from earlier builds from affecting smoke tests. Set `YR_K8S_RESET_ETCD_STATE=false` to preserve state for manual debugging.
- `datasystem` validates `etcd_address` strictly, so the K8S start scripts resolve service DNS names to IPs before rendering component configs
- `helm` is required locally for linting and rendering. If `helm` is missing, chart verification is incomplete.

## Rust data-plane routes

默认 chart 保持 `dataPlane.enabled=false`。生产部署必须配置公网入口 TLS、Edge/Node
CIDR 边界，并在启用默认 `network` 模式前完成 sandbox 受保护内网出口隔离；该出口
基线当前仍是明确待办。Buildkite smoke overlay 在隔离测试集群中启用 h2c，用于验证以下真实链路：

```text
SDK control API -> Edge Frontend Service -> Frontend loopback
SDK data API / CONNECT -> Edge Frontend Service
    -> H2 CONNECT -> Rust Node Proxy -> sandboxIP:targetPort
```

Frontend Pod 通过 `SANDBOX_ROUTER_EXTERNAL=true` 不再启动旧 Go
sandboxRouter listener；同 Pod 的 `yr start --edge` 进程接管 8080，但
Edge Frontend Service 作为统一外部入口：配置的控制面静态路由转发到同 Pod 的 Frontend，
`/direct`、`/tunnel` 和用户 HTTP 端口直接在 Edge 处理。Edge 开启时默认不渲染
Frontend Service；只有显式设置 `frontend.service.exposeWhenEdgeEnabled=true` 才保留
兼容用 ClusterIP。新增控制面路由只需修改 `dataPlane.edge.controlPlaneRoutes` 并滚动
Edge Pod，不需要修改 Rust 代码。Node DaemonSet 仍只有一个 node
容器，node session 内独立托管 `yr-node-proxy`，并通过宿主机网络访问
nested-docker 的 sandbox IP。SSH、数据库和本地端口转发由客户端 helper 在本地
适配为标准 HTTP CONNECT，复用 Edge 的 8080 HTTP entrypoint，不经过 Frontend。
默认不渲染 Traefik workload，也不启用 master provider 或 node registry。生产环境
通过 `dataPlane.edge.service` 选择 NodePort 或 LoadBalancer；Edge 在进程内终止
TLS，健康检查走独立的明文 health port。

典型生产覆盖值如下（证书 Secret 由部署系统创建和轮转）：

```yaml
traefik:
  enabled: false
frontend:
  service:
    type: ClusterIP          # internal Frontend upstream
dataPlane:
  enabled: true
  edge:
    service:
      type: LoadBalancer     # unified public entry
    tls:
      secretName: yr-edge-tls
```

The Edge Service exposes TLS `8443` for direct/tunnel/port-forwarding and
plaintext `8080` for anonymous tunnel/port-forwarding. `/direct` is never
accepted on `8080`.

Buildkite 的正式镜像步骤会先下载对应架构的
`yr-data-plane-gateway-{amd64,arm64}.tar.gz`，校验三个静态 ELF 后取出
`openyuanrong_data_plane` wheel；controlplane/node 镜像像其他组件一样通过
pip 安装该 wheel，最终目录为 `yr/data_plane/bin`。Test K8S 会先探测 Edge/Node readiness，再
运行 SDK direct、文件/目录 copy、tunnel 和 port-forwarding 用例。
