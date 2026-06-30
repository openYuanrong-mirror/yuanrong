# YR K8s Deployment Design

**Goal:** Add a new `deploy/sandbox/k8s` deployment surface that splits the current `aio-yr` all-in-one runtime into shared control-plane and node images, runs Traefik as a standalone ingress layer, embeds etcd in the deployment, and ships a Helm chart as the primary Kubernetes installation path.

**Architecture:** Reuse the current `example/aio` control-plane packaging as one shared `yr-controlplane` image for both `master` and `frontend`. Build a separate `yr-node` image for node-side runtime, Docker, supervisor, and proxy responsibilities. Deploy etcd as an in-cluster `StatefulSet`, run `master` as a `StatefulSet`, run `frontend` as a `Deployment`, run `node` as a `DaemonSet`, and run Traefik as a standalone `Deployment` exposed by a `LoadBalancer` Service. Helm is the primary delivery surface; environment-specific tuning is done with values files rather than maintaining a second independent raw-manifest stack.

**Constraints:**

- Keep the existing `example/aio` flow intact; the sandbox deployment work lives under `deploy/sandbox/k8s`.
- Follow the responsibility split and Kubernetes workload shapes observed in the `akernel` namespace, but do not reuse the `akernel` naming.
- Use `yr`-prefixed resource names, image names, scripts, and chart names.
- Bundle etcd inside the solution instead of requiring an external dependency.
- Use `StatefulSet` for `master`.
- Use `LoadBalancer` as the default Traefik exposure mode.
- Make Helm the primary install surface in this iteration.

## Approved Decisions

### 1. Deployment topology

- `etcd`: in-cluster `StatefulSet` plus headless Service
- `master`: `StatefulSet`
- `frontend`: `Deployment`
- `node`: `DaemonSet` for node-resident services
- `traefik`: standalone `Deployment` plus `LoadBalancer` Service

This mirrors the tested separation already used in the reference cluster while keeping the new deployment self-contained.

### 2. Image split and build inputs

- `yr-controlplane`
  - Derived from the current `example/aio/Dockerfile.aio-yr` control-plane dependencies.
  - Keeps Python, `yr` wheels, certificates, and shared `master`/`frontend` startup helpers.
  - Removes AIO-only process supervision, bundled Traefik binary, Docker-in-Docker setup, and runtime image tar loading.
  - Reused by `master` and `frontend`; Helm selects behavior with the container command.
  - Connects to in-cluster etcd through Kubernetes service discovery.
- `yr-node`
  - Separate image for node runtime, proxy, and host-integration responsibilities.
  - Keeps Docker, supervisor, host integration, and node-plane startup behavior out of the shared control-plane image.

The intent is to split by runtime responsibility without over-fragmenting images whose only difference would be entrypoint selection.

The first implementation must make the image build contract explicit:

- `make all` remains the prerequisite producer of compiled artifacts.
- `deploy/sandbox/k8s/build-images.sh` validates required inputs directly from repository `output/`.
- Required `output/` artifacts for v1:
  - `openyuanrong-*.whl`
  - `openyuanrong_sdk*.whl`
  - `runtime-launcher`
- `yr-controlplane` consumes the Python wheels.
- `yr-node` derives from `yr-controlplane` and adds node-only runtime dependencies.
- `build-images.sh` must fail fast with a clear error if the required artifacts are missing.

### 3. Delivery structure

Create a new directory:

```text
deploy/sandbox/k8s/
  README.md
  build-images.sh
  images/
    Dockerfile.controlplane-base
    Dockerfile.node
  bin/
    start-master.sh
    start-frontend.sh
    start-node.sh
    supervisord-node-entrypoint.sh
  charts/
    yr-k8s/
      Chart.yaml
      values.yaml
      templates/
        _helpers.tpl
        namespace.yaml
        secrets.yaml
        etcd-statefulset.yaml
        etcd-service.yaml
        master-statefulset.yaml
        master-service.yaml
        frontend-deployment.yaml
        frontend-service.yaml
        node-daemonset.yaml
        traefik-configmap.yaml
        traefik-deployment.yaml
        traefik-service.yaml
  k8s/
    values.local.yaml
    values.prod.yaml
```

The Helm chart is the authoritative deployment surface. The `k8s/` directory only stores values overlays, not a duplicated raw-manifest stack. The image count remains two families: shared `yr-controlplane` plus node-only `yr-node`.

### 4. Executable process contract

The v1 implementation uses the repository-supported `yr start --block true -e` surface and selects each workload role with explicit flags.

Required role entrypoints:

- `bin/start-master.sh`
  - Executes `yr start --master --block true -e` with scheduler, meta-service, and IAM enabled.
- `bin/start-frontend.sh`
  - Executes `yr start --block true -e` with `--enable_faas_frontend true`.
- `bin/start-node.sh`
  - Executes `yr start --block true -e` from the node supervisor entrypoint.

This keeps the chart aligned with the existing CLI startup surface instead of inventing a third process model.

## Runtime and configuration model

### etcd

- Default to a single replica for the first version.
- Expose a headless Service for stable network identity.
- Keep chart values open for later expansion to a three-node etcd cluster.
- Store etcd persistence, resources, and service configuration in Helm values.

### master

- Run as a `StatefulSet` even when the default replica count is `1`.
- Expose the ports needed by control-plane clients.
- Read etcd address from the in-cluster Service instead of expecting a local daemon.
- The `master` workload only owns `function_master`.
- Scheduler, meta-service, and IAM run inside the master startup path for this sandbox deployment surface.

### frontend

- Run as a separate `Deployment`.
- Disable non-frontend control-plane responsibilities through startup wiring.
- Point `META_SERVICE_ADDRESS` and `IAM_SERVER_ADDRESS` at the master access Service.
- Continue pointing router/meta etcd configuration at the in-cluster etcd Service.
- Keep the existing frontend assumptions about node-plane ports explicit: it depends on `FUNCTION_PROXY_PORT`, `FUNCTION_PROXY_GRPC_PORT`, and `DS_WORKER_PORT` values supplied through chart values and config.
- Expose an internal `ClusterIP` Service for Traefik to route to.

### node

- `yr-node` runs one pod per Kubernetes node for node-resident services.
- Run the node-resident part as a `DaemonSet`.
- Avoid privileged execution unless a concrete node bootstrap requirement proves it necessary.
- Use `hostNetwork: true` in v1 to match the existing function-proxy data-plane port model.
- Expose host ports for the node-plane ports consumed by frontend and cluster routing.
- Keep the required hostPath and config mounts explicit in the chart:
  - persistent node work directory such as `/home/yr` or the repo-equivalent runtime root
  - `/dev`
  - `/dev/shm` via `emptyDir`
  - node bootstrap/config files from ConfigMaps and Secrets
- Read etcd address from the in-cluster Service.
- Preserve node bootstrap scripts and host integration instead of trying to fold them into the control-plane images.
- Use a dedicated ServiceAccount in the chart; add RBAC only if the chosen node bootstrap flow proves it is required during implementation.
- Exact v1 pod composition:
  - `node-daemonset`: one container from `yr-node`, default entrypoint `bin/supervisord-node-entrypoint.sh`
- This preserves the repository's split between control-plane packaging and node-resident proxy/bootstrap concerns while limiting the work to two image families.

### traefik

- Run as an independent `Deployment`.
- Use a `LoadBalancer` Service by default.
- Read static configuration from ConfigMaps and dynamic routing data from etcd.
- Consume TLS material from Secrets.

### Reference baseline

The implementation should align with two existing reference surfaces:

- Repository templates under `deploy/k8s/charts/openyuanrong/templates/` for component-level launch contracts and port wiring.
- The observed `akernel` namespace shape from 2026-04-19:
  - etcd as `StatefulSet`
  - frontend separate from master
  - standalone Traefik with `LoadBalancer`
  - independent node plane

## Helm values surface

`values.yaml` should make these groups adjustable:

- global naming, namespace, image registry, image tags, pull secrets
- etcd replicas, storage class, PVC size, resources
- master replicas, resources, service ports, IAM toggles
- frontend replicas, resources, service ports
- node image, security context, hostPath mounts, tolerations, selectors
- node hostNetwork and hostPorts for function-proxy and worker-facing endpoints
- traefik service type, load balancer annotations, TLS secret, etcd root key, entrypoints
- certificate and secret references
- environment-specific overrides for local and production overlays

The first implementation should optimize for one clean path to install, inspect, and override rather than covering every production toggle.

## Validation targets

- Build scripts can produce `yr-controlplane` and `yr-node` images from the new directory.
- `build-images.sh` documents and validates its required `output/` inputs.
- The chart renders concrete workloads for `master`, `frontend`, `node-daemonset`, `traefik`, and `etcd`.
- The Helm chart renders without missing required values.
- Rendered manifests contain:
  - `StatefulSet` for etcd
  - `StatefulSet` for master
  - `Deployment` for frontend
  - `DaemonSet` for node
  - `Deployment` and `LoadBalancer` Service for Traefik
- Traefik static config points at the in-cluster etcd Service.
- Frontend points at the master access Service for meta and IAM ports, not localhost assumptions.
- Local verification target:
  - build the two image families
  - run `helm lint`
  - run `helm template` with both `values.local.yaml` and `values.prod.yaml`
- Smoke target when a disposable cluster is available:
  - `helm install` into a temporary namespace
  - wait for etcd, master, frontend, traefik, and one node-daemonset pod to become Ready
  - verify Traefik can serve frontend `/healthz`
  - verify frontend can reach master meta and IAM ports
  - verify node registration keys appear in etcd
- The new directory does not regress the existing `example/aio` workflow.

## Files in scope

- Files under `deploy/sandbox/k8s/`
- Supporting tests that validate the new directory layout, image split, chart structure, and key config expectations
- Minimal documentation updates that reference the new deployment surface where appropriate

## Out of scope

- Replacing the existing `example/aio` deployment
- Full high-availability etcd for this first cut
- A second non-Helm manifest maintenance path
- Unrelated cleanup of the older Kubernetes chart stack under `deploy/k8s/charts/openyuanrong`
