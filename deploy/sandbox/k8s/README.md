# yr-k8s

`deploy/sandbox/k8s` is the Kubernetes deployment surface for the split `yr` images and Helm chart tracked in `docs/features/2026-04-19-yr-k8s-design.md`.

This directory currently contains:

- layered image build scaffolding for `yr-base`, `yr-compile`, `yr-runtime`, `yr-controlplane`, and `yr-node`
- `yr start --block` entrypoint wrappers for `master`, `frontend`, and `node`
- a Helm chart for the three active workloads plus support objects and Traefik
- local and production values overlays

## Build inputs

Run `make all` from the repository root before invoking `deploy/sandbox/k8s/build-images.sh`.

The build script validates artifacts in the repository root `output/` directory, then builds local layered images. `yr-base` owns the shared Ubuntu/Python/runtime-library layer, `yr-compile` adds compile tools, `yr-controlplane` installs the control-plane wheels and entrypoints, `yr-node` adds node-only Docker/supervisor wiring, and `yr-runtime` installs only the SDK wheel needed by function containers. Master and frontend share `yr-controlplane`; their behavior is selected by the Helm command. Runtime function containers use `yr-runtime` through the generated `services.yaml`. It still fails fast when required artifacts are missing.

Required `output/` artifacts:

- `openyuanrong-*.whl`
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
YR_ENABLE_TLS=false bash test/st/run_off_cluster_test.sh -a <traefik-ip>:18888 -- -m smoke
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

- the active workload model is `master`, `frontend`, and `node`
- `master` uses `yr start --master --block true -e` and additionally enables scheduler, meta-service, and iam-server
- `frontend` uses `yr start --block true -e --enable_faas_frontend true`
- `node` uses `yr start --block true -e`
- `yr-runtime` is pushed as its own image and referenced by the `py39` runtime rootfs
- `etcd` is external in this model and is passed in through `global.externalEtcd`
- `datasystem` validates `etcd_address` strictly, so local deployments should use an IP or full service FQDN such as `yr-etcd.yr.svc.cluster.local:2379`, not a bare short service name
- `helm` is required locally for linting and rendering. If `helm` is missing, chart verification is incomplete.
