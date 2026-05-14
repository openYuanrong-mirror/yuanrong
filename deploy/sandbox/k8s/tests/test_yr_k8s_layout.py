import pathlib
import re
import stat
import subprocess
import tempfile
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]
HELM_BIN = pathlib.Path("/home/wyc/.local/bin/helm")
RELEASE = "yr-k8s"
NAMESPACE = "yr-k8s"

ACTIVE_SCRIPTS = [
    "bin/start-master.sh",
    "bin/start-frontend.sh",
    "bin/start-node.sh",
    "bin/supervisord-node-entrypoint.sh",
    "smoke.py",
]

RETIRED_SCRIPTS = [
    "bin/start-scheduler.sh",
    "bin/start-meta-service.sh",
    "bin/start-iam.sh",
    "bin/start-runtime-manager.sh",
    "bin/start-function-agent.sh",
    "bin/start-function-proxy.sh",
    "bin/start-ds-worker.sh",
]

ACTIVE_TEMPLATES = [
    "charts/yr-k8s/templates/_helpers.tpl",
    "charts/yr-k8s/templates/namespace.yaml",
    "charts/yr-k8s/templates/secrets.yaml",
    "charts/yr-k8s/templates/components-configmap.yaml",
    "charts/yr-k8s/templates/services-configmap.yaml",
    "charts/yr-k8s/templates/etcd-statefulset.yaml",
    "charts/yr-k8s/templates/etcd-service.yaml",
    "charts/yr-k8s/templates/master-serviceaccount.yaml",
    "charts/yr-k8s/templates/master-role.yaml",
    "charts/yr-k8s/templates/master-rolebinding.yaml",
    "charts/yr-k8s/templates/master-statefulset.yaml",
    "charts/yr-k8s/templates/master-service.yaml",
    "charts/yr-k8s/templates/node-serviceaccount.yaml",
    "charts/yr-k8s/templates/node-role.yaml",
    "charts/yr-k8s/templates/node-rolebinding.yaml",
    "charts/yr-k8s/templates/node-daemonset.yaml",
    "charts/yr-k8s/templates/frontend-deployment.yaml",
    "charts/yr-k8s/templates/frontend-service.yaml",
    "charts/yr-k8s/templates/traefik-configmap.yaml",
    "charts/yr-k8s/templates/traefik-dynamic-configmap.yaml",
    "charts/yr-k8s/templates/traefik-deployment.yaml",
    "charts/yr-k8s/templates/traefik-service.yaml",
]

RETIRED_TEMPLATES = [
    "charts/yr-k8s/templates/agent-pool-deployment.yaml",
    "charts/yr-k8s/templates/frontend-configmap.yaml",
    "charts/yr-k8s/templates/function-agent-configmap.yaml",
    "charts/yr-k8s/templates/iam-deployment.yaml",
    "charts/yr-k8s/templates/iam-policy-config.yaml",
    "charts/yr-k8s/templates/iam-service.yaml",
    "charts/yr-k8s/templates/meta-service-configmap.yaml",
    "charts/yr-k8s/templates/meta-service-deployment.yaml",
    "charts/yr-k8s/templates/meta-service-service.yaml",
    "charts/yr-k8s/templates/scheduler-configmap.yaml",
    "charts/yr-k8s/templates/scheduler-deployment.yaml",
    "charts/yr-k8s/templates/scheduler-role.yaml",
    "charts/yr-k8s/templates/scheduler-rolebinding.yaml",
    "charts/yr-k8s/templates/scheduler-service.yaml",
    "charts/yr-k8s/templates/scheduler-serviceaccount.yaml",
]


def assert_paths_exist(test_case: unittest.TestCase, relative_paths: list[str]) -> None:
    for relative_path in relative_paths:
        with test_case.subTest(path=relative_path):
            test_case.assertTrue((ROOT / relative_path).exists(), f"{relative_path} should exist")


def assert_paths_absent(test_case: unittest.TestCase, relative_paths: list[str]) -> None:
    for relative_path in relative_paths:
        with test_case.subTest(path=relative_path):
            test_case.assertFalse((ROOT / relative_path).exists(), f"{relative_path} should be removed")


def load_yaml_file(path: pathlib.Path):
    return yaml.safe_load(path.read_text())


def render_chart(*extra_args: str) -> list[dict]:
    result = subprocess.run(
        [
            str(HELM_BIN),
            "template",
            RELEASE,
            str(ROOT / "charts/yr-k8s"),
            "--namespace",
            NAMESPACE,
            *extra_args,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def find_manifest(manifests: list[dict], kind: str, name: str) -> dict:
    for manifest in manifests:
        if manifest.get("kind") == kind and manifest.get("metadata", {}).get("name") == name:
            return manifest
    raise AssertionError(f"{kind} {name} should exist")


def find_container(manifest: dict, container_name: str) -> dict:
    for container in manifest["spec"]["template"]["spec"]["containers"]:
        if container["name"] == container_name:
            return container
    raise AssertionError(f"container {container_name} should exist")


def find_env(container: dict, name: str) -> str:
    for env_var in container.get("env", []):
        if env_var["name"] == name:
            return env_var["value"]
    raise AssertionError(f"env {name} should exist")


def expected_image(values: dict, image_name: str) -> str:
    if image_name in values["global"]["images"]:
        image = values["global"]["images"][image_name]
    else:
        image = values[image_name]["image"]
    registry = image.get("registry", values["global"]["imageRegistry"]).rstrip("/")
    return f"{registry}/{image['repository']}:{image['tag']}"


def expected_etcd_addr(values: dict) -> str:
    if values["global"]["externalEtcd"]["addrList"]:
        return values["global"]["externalEtcd"]["addrList"]
    return f"yr-etcd.{NAMESPACE}.svc.cluster.local:{values['etcd']['service']['port']}"


class YrK8sLayoutTests(unittest.TestCase):
    def test_surface_tree_matches_three_workload_model(self):
        assert_paths_exist(
            self,
            [
                "README.md",
                "build-images.sh",
                "push-images-swr.sh",
                "deploy.sh",
                "../images/Dockerfile.base",
                "../images/Dockerfile.compile",
                "images/Dockerfile.controlplane-base",
                "images/Dockerfile.node",
                "images/Dockerfile.runtime",
                "images/supervisord-node.conf",
                "charts/yr-k8s/Chart.yaml",
                "charts/yr-k8s/values.yaml",
                "k8s/values.local.yaml",
                "k8s/values.prod.yaml",
                *ACTIVE_SCRIPTS,
                *ACTIVE_TEMPLATES,
            ],
        )
        assert_paths_absent(
            self,
            RETIRED_SCRIPTS
            + RETIRED_TEMPLATES
            + [
                "images/Dockerfile.master",
                "images/Dockerfile.frontend",
            ],
        )

    def test_build_and_readme_document_real_image_builds(self):
        build_script = (ROOT / "build-images.sh").read_text()
        package_script = (ROOT.parents[2] / ".buildkite/package_sandbox_release.sh").read_text()
        pipeline = (ROOT.parents[2] / ".buildkite/pipeline.dynamic.yml").read_text()
        push_script = (ROOT / "push-images-swr.sh").read_text()
        controlplane_dockerfile = (ROOT / "images/Dockerfile.controlplane-base").read_text()
        runtime_dockerfile = (ROOT / "images/Dockerfile.runtime").read_text()
        readme = (ROOT / "README.md").read_text().lower()

        for token in [
            "output",
            ".yr-k8s-deploy",
            "docker build",
            "yr-base",
            "yr-runtime",
            "yr-compile",
            "yr-controlplane",
            "yr-node",
            "yr-runtime",
            "--cache-from",
            "BUILDKIT_INLINE_CACHE=1",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, build_script)

        self.assertIn('YR_K8S_IMAGE_CACHE: "1"', pipeline)
        self.assertIn("build-cache", push_script)
        self.assertIn("Updating image cache", push_script)
        self.assertIn("bash deploy/sandbox/k8s/build-images.sh", readme)
        self.assertIn("push-images-swr.sh", readme)
        self.assertIn("multi-architecture manifest tag", readme)
        self.assertIn("deploy.sh", readme)
        self.assertIn("run_off_cluster_test.sh", readme)
        self.assertNotIn("pkg/", readme)
        self.assertNotIn("scaffold only", readme)
        self.assertIn("cp output/openyuanrong-*.tar.gz artifacts/release/", pipeline)
        self.assertNotIn("cp output/*.tar.gz artifacts/release/", pipeline)
        self.assertNotIn("cp datasystem/output/*.tar.gz artifacts/release/", pipeline)
        self.assertNotIn("yr-frontend*.tar.gz", build_script)
        self.assertNotIn("yr-frontend*.tar.gz", package_script)
        self.assertNotIn("yr-frontend*.tar.gz", controlplane_dockerfile)
        self.assertIn("artifacts/release/openyuanrong-*.whl", package_script)
        self.assertIn("artifacts/openyuanrong-sdk/${IMAGE_SDK_WHEEL_PATTERN}", package_script)
        self.assertNotIn("runtime-launcher", package_script)
        self.assertNotIn("artifacts/release/*", package_script)
        self.assertIn("COPY openyuanrong-*.whl", controlplane_dockerfile)
        self.assertIn("COPY openyuanrong_sdk*.whl", controlplane_dockerfile)
        self.assertNotIn("COPY runtime-launcher", controlplane_dockerfile)
        self.assertIn("ARG BASE_IMAGE=yr-base", controlplane_dockerfile)
        self.assertIn("FROM ${BASE_IMAGE}", controlplane_dockerfile)
        self.assertIn('ln -sf "${python_bin_dir}/yr" /usr/local/bin/yr', controlplane_dockerfile)
        self.assertIn('ln -sf "${python_bin_dir}/yrcli" /usr/local/bin/yrcli', controlplane_dockerfile)
        self.assertIn("https://mirrors.aliyun.com/pypi/simple", controlplane_dockerfile)
        self.assertIn("--trusted-host mirrors.aliyun.com", controlplane_dockerfile)
        self.assertIn("COPY .yr-k8s-deploy/bin/start-master.sh", controlplane_dockerfile)
        self.assertIn("COPY .yr-k8s-deploy/bin/start-frontend.sh", controlplane_dockerfile)
        self.assertIn("ARG BASE_IMAGE=yr-base", runtime_dockerfile)
        self.assertIn("FROM ${BASE_IMAGE}", runtime_dockerfile)
        self.assertIn("COPY openyuanrong_sdk*.whl", runtime_dockerfile)
        self.assertIn("pip install --no-cache-dir /tmp/openyuanrong_sdk*.whl", runtime_dockerfile)
        self.assertNotIn("openyuanrong-*.whl", runtime_dockerfile)
        self.assertNotIn("CONTROLPLANE_IMAGE", runtime_dockerfile)
        runtime_builds = re.findall(
            r'build_image "\$\{RUNTIME_IMAGE\}".*?--build-arg BASE_IMAGE="\$\{BASE_IMAGE\}"',
            build_script,
            re.S,
        )
        self.assertGreaterEqual(len(runtime_builds), 1)
        for runtime_build in runtime_builds:
            self.assertNotIn("CONTROLPLANE_IMAGE", runtime_build)
        self.assertNotIn("images/Dockerfile.master", build_script)
        self.assertNotIn("images/Dockerfile.frontend", build_script)
        self.assertNotIn("yr-controlplane-base", build_script)
        self.assertNotIn(" AS python-builder", controlplane_dockerfile)

    def test_container_ep_only_lives_in_node_image(self):
        controlplane_base = (ROOT / "images/Dockerfile.controlplane-base").read_text()
        node_dockerfile = (ROOT / "images/Dockerfile.node").read_text()
        node_supervisord = (ROOT / "images/supervisord-node.conf").read_text()
        node_entrypoint = (ROOT / "bin/supervisord-node-entrypoint.sh").read_text()

        self.assertNotIn("CONTAINER_EP=", controlplane_base)
        self.assertIn("CONTAINER_EP=", node_dockerfile)
        self.assertIn("ARG CONTROLPLANE_IMAGE=yr-controlplane", node_dockerfile)
        self.assertIn("supervisor", node_dockerfile)
        self.assertIn("docker.io", node_dockerfile)
        self.assertIn("supervisord-node-entrypoint.sh", node_dockerfile)
        self.assertNotIn("[program:runtime-launcher]", node_supervisord)
        self.assertIn("[program:yr-node]", node_supervisord)
        self.assertIn("dockerd", node_entrypoint)
        self.assertIn("docker info", node_entrypoint)

    def test_start_scripts_use_yr_start_block_model(self):
        expectations = {
            "bin/start-master.sh": [
                "/usr/local/bin/yr start",
                "--master",
                "--block true",
                "-e",
                "--port_policy FIX",
                "--etcd_mode outter",
                "--enable_function_scheduler true",
                "--enable_meta_service true",
                "--enable_iam_server true",
                "--cpu_num",
                "controlplane_cpu_num",
            ],
            "bin/start-frontend.sh": [
                "/usr/local/bin/yr start",
                "--block true",
                "-e",
                "--port_policy FIX",
                "--etcd_mode outter",
                "--enable_faas_frontend true",
                "--cpu_num",
                "controlplane_cpu_num",
            ],
            "bin/start-node.sh": [
                "/usr/local/bin/yr start",
                "--block true",
                "-e",
                "--port_policy FIX",
                "--etcd_mode outter",
                "--enable_runtime_launcher true",
            ],
        }
        for relative_path, tokens in expectations.items():
            path = ROOT / relative_path
            text = path.read_text()
            mode = path.stat().st_mode
            with self.subTest(path=relative_path):
                self.assertTrue(mode & stat.S_IXUSR, f"{relative_path} should be executable")
                self.assertTrue(text.startswith("#!/usr/bin/env bash"))
                self.assertIn("set -euo pipefail", text)
                self.assertNotIn("python3 -m yr.cli.main", text)
                self.assertNotIn("--runtime_launcher_sock", text)
                for token in tokens:
                    self.assertIn(token, text)

    def test_values_surface_matches_embedded_etcd_model(self):
        values = load_yaml_file(ROOT / "charts/yr-k8s/values.yaml")

        for section in ["global", "etcd", "master", "frontend", "node", "traefik", "debug"]:
            self.assertIn(section, values)
        for retired in ["scheduler", "meta-service", "iam", "agent-pool"]:
            self.assertNotIn(retired, values)

        self.assertIn("externalEtcd", values["global"])
        self.assertEqual(values["global"]["externalEtcd"]["addrList"], "")
        self.assertTrue(values["etcd"]["enabled"])
        self.assertFalse(values["etcd"]["persistence"]["enabled"])
        self.assertEqual(sorted(values["global"]["images"].keys()), ["controlplane", "node", "runtime", "traefik"])
        self.assertIn("global.images.runtime", values["global"]["services"]["servicesYaml"])
        self.assertIn("imageurl", values["global"]["services"]["servicesYaml"])
        self.assertEqual(
            sorted(values["node"]["ports"].keys()),
            ["dsWorker", "functionProxy", "functionProxyGrpc"],
        )

    def test_rendered_manifests_match_three_workload_model(self):
        values = load_yaml_file(ROOT / "charts/yr-k8s/values.yaml")
        manifests = render_chart()

        names = {doc["metadata"]["name"] for doc in manifests if "metadata" in doc}
        master_name = "yr-master"
        master_headless_name = "yr-master-headless"
        master_access_name = "yr-master-access"
        frontend_name = "yr-frontend"
        node_name = "yr-node"
        traefik_name = "yr-traefik"
        etcd_name = "yr-etcd"
        services_name = "yr-services"
        etcd_addr = expected_etcd_addr(values)

        for retired_name in [
            "yr-scheduler",
            "yr-meta-service",
            "yr-iam-adaptor",
            "yr-agent-pool",
        ]:
            self.assertNotIn(retired_name, names)

        etcd_sts = find_manifest(manifests, "StatefulSet", etcd_name)
        etcd_svc = find_manifest(manifests, "Service", etcd_name)
        master_sts = find_manifest(manifests, "StatefulSet", master_name)
        master_headless_svc = find_manifest(manifests, "Service", master_headless_name)
        master_access_svc = find_manifest(manifests, "Service", master_access_name)
        frontend_dep = find_manifest(manifests, "Deployment", frontend_name)
        frontend_svc = find_manifest(manifests, "Service", frontend_name)
        node_ds = find_manifest(manifests, "DaemonSet", node_name)
        traefik_dep = find_manifest(manifests, "Deployment", traefik_name)
        traefik_svc = find_manifest(manifests, "Service", traefik_name)
        services_cm = find_manifest(manifests, "ConfigMap", services_name)

        etcd_container = find_container(etcd_sts, "etcd")
        self.assertEqual(etcd_sts["spec"]["serviceName"], etcd_name)
        self.assertEqual(etcd_container["image"], expected_image(values, "etcd"))
        self.assertEqual(etcd_container["ports"][0]["containerPort"], values["etcd"]["service"]["port"])
        self.assertIn(f"--advertise-client-urls=http://{etcd_addr}", etcd_container["args"])
        self.assertEqual(etcd_svc["spec"]["ports"][0]["port"], values["etcd"]["service"]["port"])

        self.assertEqual(master_sts["spec"]["serviceName"], master_headless_name)
        self.assertEqual(master_headless_svc["spec"]["clusterIP"], "None")
        self.assertEqual(
            [p["port"] for p in master_headless_svc["spec"]["ports"]],
            [
                values["master"]["service"]["ports"]["master"],
                values["master"]["service"]["ports"]["metaService"],
                values["master"]["service"]["ports"]["iamServer"],
            ],
        )
        self.assertNotIn("clusterIP", master_access_svc["spec"])
        self.assertEqual(
            [p["port"] for p in master_access_svc["spec"]["ports"]],
            [
                values["master"]["service"]["ports"]["master"],
                values["master"]["service"]["ports"]["metaService"],
                values["master"]["service"]["ports"]["iamServer"],
            ],
        )
        self.assertIn("services.yaml", services_cm["data"])
        self.assertIn(expected_image(values, "runtime"), services_cm["data"]["services.yaml"])

        master_container = find_container(master_sts, "master")
        controlplane_image = expected_image(values, "controlplane")
        self.assertEqual(master_container["image"], controlplane_image)
        self.assertEqual(master_container["command"], ["/usr/local/bin/start-master.sh"])
        self.assertEqual(find_env(master_container, "YR_ETCD_ADDR_LIST"), etcd_addr)
        master_mounts = {m["mountPath"] for m in master_container.get("volumeMounts", [])}
        self.assertIn(values["debug"]["sidecar"]["sessionDir"], master_mounts)

        frontend_container = find_container(frontend_dep, "frontend")
        self.assertEqual(frontend_container["image"], controlplane_image)
        self.assertEqual(frontend_container["command"], ["/usr/local/bin/start-frontend.sh"])
        self.assertEqual(find_env(frontend_container, "YR_MASTER_IP"), master_access_name)
        self.assertEqual(find_env(frontend_container, "YR_FAAS_FRONTEND_HTTP_PORT"), str(values["frontend"]["faasFrontend"]["httpPort"]))
        self.assertEqual(find_env(frontend_container, "YR_ETCD_ADDR_LIST"), etcd_addr)
        self.assertEqual(find_env(frontend_container, "YR_META_SERVICE_ADDRESS"), f"{master_access_name}:31111")
        self.assertEqual(find_env(frontend_container, "IAM_SERVER_ADDRESS"), f"{master_access_name}:31112")
        self.assertEqual(find_env(frontend_container, "FUNCTION_PROXY_PORT"), str(values["node"]["ports"]["functionProxy"]["containerPort"]))
        self.assertEqual(find_env(frontend_container, "FUNCTION_PROXY_GRPC_PORT"), str(values["node"]["ports"]["functionProxyGrpc"]["containerPort"]))
        self.assertEqual(find_env(frontend_container, "DS_WORKER_PORT"), str(values["node"]["ports"]["dsWorker"]["containerPort"]))
        self.assertEqual(frontend_container["resources"], values["frontend"]["resources"])
        self.assertEqual(frontend_svc["spec"]["ports"][0]["port"], values["frontend"]["service"]["port"])
        frontend_mounts = {m["mountPath"] for m in frontend_container.get("volumeMounts", [])}
        self.assertIn("/home/sn/service-config/services.yaml", frontend_mounts)
        self.assertIn("/etc/yuanrong/config.toml", frontend_mounts)
        self.assertIn(values["debug"]["sidecar"]["sessionDir"], frontend_mounts)
        self.assertNotIn("/home/sn/iam-config", frontend_mounts)

        node_container = find_container(node_ds, "node")
        self.assertEqual(node_container["image"], expected_image(values, "node"))
        self.assertNotIn("command", node_container)
        self.assertTrue(node_ds["spec"]["template"]["spec"]["hostNetwork"])
        self.assertEqual(node_container["securityContext"], values["node"]["securityContext"])
        self.assertEqual(
            node_container["readinessProbe"]["initialDelaySeconds"],
            values["node"]["probes"]["readiness"]["initialDelaySeconds"],
        )
        self.assertEqual(
            node_container["livenessProbe"]["initialDelaySeconds"],
            values["node"]["probes"]["liveness"]["initialDelaySeconds"],
        )
        self.assertEqual(find_env(node_container, "YR_MASTER_IP"), master_access_name)
        self.assertEqual(find_env(node_container, "YR_ETCD_ADDR_LIST"), etcd_addr)
        self.assertEqual(find_env(node_container, "DOCKER_DRIVER"), values["node"]["docker"]["storageDriver"])
        self.assertEqual(node_container["resources"], values["node"]["resources"])
        self.assertEqual(
            sorted(p["hostPort"] for p in node_container["ports"]),
            sorted([
                values["node"]["ports"]["functionProxy"]["hostPort"],
                values["node"]["ports"]["functionProxyGrpc"]["hostPort"],
                values["node"]["ports"]["dsWorker"]["hostPort"],
            ]),
        )
        node_mounts = {m["mountPath"] for m in node_container.get("volumeMounts", [])}
        self.assertNotIn("/proc/1", node_mounts)
        self.assertIn(values["debug"]["sidecar"]["sessionDir"], node_mounts)
        self.assertIn("/var/lib/docker", node_mounts)
        node_volumes = {v["name"]: v for v in node_ds["spec"]["template"]["spec"]["volumes"]}
        self.assertEqual(node_volumes["docker-root"]["hostPath"]["path"], values["node"]["docker"]["rootHostPath"])

        traefik_cfg = find_manifest(manifests, "ConfigMap", "yr-traefik-configmap")
        traefik_dynamic_cfg = find_manifest(manifests, "ConfigMap", "yr-traefik-dynamic")
        traefik_text = traefik_cfg["data"]["traefik.yaml"]
        traefik_dynamic_text = traefik_dynamic_cfg["data"]["config.yml"]
        self.assertIn(etcd_addr, traefik_text)
        self.assertIn(values["traefik"]["etcd"]["rootKey"], traefik_text)
        self.assertIn("/etc/traefik/dynamic", traefik_text)
        self.assertIn(frontend_name, traefik_dynamic_text)
        self.assertIn("/api/sandbox", traefik_dynamic_text)
        self.assertIn("/serverless/v1/componentshealth", traefik_dynamic_text)
        self.assertIn("/invocations", traefik_dynamic_text)
        self.assertEqual(find_container(traefik_dep, "traefik")["image"], expected_image(values, "traefik"))
        self.assertEqual(traefik_svc["spec"]["ports"][0]["port"], values["traefik"]["service"]["port"])

        for manifest in [master_sts, frontend_dep, node_ds]:
            debug_container = find_container(manifest, "debug-busybox")
            debug_image = values["debug"]["sidecar"]["image"]
            debug_registry = debug_image["registry"].rstrip("/")
            self.assertEqual(debug_container["image"], f"{debug_registry}/{debug_image['repository']}:{debug_image['tag']}")
            self.assertFalse(debug_container["securityContext"]["privileged"])
            self.assertFalse(debug_container["securityContext"]["allowPrivilegeEscalation"])
            debug_mounts = {m["mountPath"] for m in debug_container.get("volumeMounts", [])}
            self.assertIn(values["debug"]["sidecar"]["sessionDir"], debug_mounts)

        override_manifests = render_chart("--set", "frontend.iamServerAddress=iam.example.com:31112")
        override_frontend = find_manifest(override_manifests, "Deployment", frontend_name)
        override_frontend_container = find_container(override_frontend, "frontend")
        self.assertEqual(find_env(override_frontend_container, "IAM_SERVER_ADDRESS"), "iam.example.com:31112")

    def test_pipeline_deploys_published_sandbox_release_to_target_k8s(self):
        bootstrap_pipeline = (ROOT.parents[2] / ".buildkite/pipeline.yml").read_text()
        pipeline = (ROOT.parents[2] / ".buildkite/pipeline.dynamic.yml").read_text()
        deploy_script = (ROOT.parents[2] / ".buildkite/test_sandbox_k8s.sh").read_text()
        yuanrong_ci_values = load_yaml_file(ROOT.parents[2] / "deploy/helm/yuanrong-ci/values.yaml")
        agent_stack_values = load_yaml_file(ROOT.parents[2] / "deploy/helm/agent-stack-k8s-values.yaml")
        deploy_script_k8s = (ROOT / "deploy.sh").read_text()

        self.assertIn("Initialize", bootstrap_pipeline)
        self.assertIn("Build X86", pipeline)
        self.assertIn("Build Image", pipeline)
        self.assertIn("publish-sandbox-release-amd64", pipeline)
        self.assertIn("publish-sandbox-release-arm64", pipeline)
        self.assertIn("publish-sandbox-manifest", pipeline)
        self.assertIn("package_sandbox_manifest.sh", pipeline)
        self.assertIn('SANDBOX_FINAL_PACKAGE_STEP="publish-sandbox-manifest"', pipeline)
        self.assertIn('SANDBOX_PACKAGE_STEP_KEY: "${SANDBOX_FINAL_PACKAGE_STEP}"', pipeline)
        arm_image_step = re.search(
            r'- label: ":package: Build Image arm".*?(?=\n  - label:|\ncase "\$\\{ENABLE_MACOS_SDK\\}")',
            pipeline,
            re.S,
        )
        self.assertIsNotNone(arm_image_step)
        self.assertIn('image: "$BUILDER_IMAGE"', arm_image_step.group(0))
        self.assertNotIn('image: "$SANDBOX_PACKAGER_IMAGE"', arm_image_step.group(0))
        self.assertIn('YR_K8S_DOCKER_BUILDKIT: "0"', arm_image_step.group(0))
        self.assertIn("Test K8S", pipeline)
        self.assertIn('key: "test-k8s"', pipeline)
        self.assertIn('key: "build-all-arm64"', pipeline)
        self.assertIn("Build arm", pipeline)
        self.assertNotIn("Build macOS", pipeline)
        self.assertNotIn('key: "build-macos-arm64"', pipeline)
        self.assertIn('depends_on: "${SANDBOX_FINAL_PACKAGE_STEP}"', pipeline)
        self.assertIn("test_sandbox_k8s.sh", pipeline)
        self.assertNotIn("deploy_sandbox_beijing4.sh", pipeline)
        self.assertNotIn("sandbox-target-kubeconfig", pipeline)
        self.assertNotIn("YR_K8S_KUBECONFIG", pipeline)
        self.assertNotIn("Initialize and Load", bootstrap_pipeline)
        self.assertNotIn("Build All", pipeline)
        self.assertNotIn("Publish sandbox release", pipeline)
        self.assertNotIn("Deploy sandbox to Beijing4", pipeline)
        self.assertNotIn("Build macOS SDK", pipeline)
        self.assertIn("deploy.sh", deploy_script)
        self.assertNotIn("deploy-beijing4.sh", deploy_script)
        self.assertIn('KUBECONFIG_PATH="/var/run/yr-k8s/target/kubeconfig"', deploy_script)
        self.assertNotIn("YR_K8S_KUBECONFIG:-", deploy_script)
        self.assertIn("YR_K8S_ROLLOUT_TIMEOUT:-20m", deploy_script_k8s)
        self.assertIn("prepull_runtime_image", deploy_script_k8s)
        self.assertIn("docker pull", deploy_script_k8s)
        self.assertIn("run_off_cluster_test.sh", deploy_script)
        self.assertIn("artifacts/release/openyuanrong-*.whl", deploy_script)
        self.assertIn("artifacts/openyuanrong-sdk/${SMOKE_SDK_WHEEL_PATTERN}", deploy_script)
        self.assertNotIn('artifact download "artifacts/release/*"', deploy_script)
        self.assertIn("YR_K8S_SMOKE_PIP_INDEX_URL", deploy_script)
        self.assertIn("-m smoke", deploy_script)
        self.assertIn("YR_OFF_CLUSTER_TEST_TIMEOUT", deploy_script)
        self.assertIn("cp output/openyuanrong-*.whl artifacts/release/", pipeline)
        self.assertNotIn("cp datasystem/output/*.whl artifacts/release/", pipeline)
        self.assertNotIn("cp datasystem/output/sdk/*.whl artifacts/release/", pipeline)
        self.assertNotIn("cp functionsystem/output/*.whl artifacts/release/", pipeline)
        self.assertIn("TEST_PYPI_API_TOKEN", pipeline)
        self.assertIn("test-pypi-credentials", pipeline)
        self.assertIn("openyuanrong_sdk-*.whl", pipeline)
        self.assertIn("https://test.pypi.org/legacy/", pipeline)
        self.assertNotIn("twine upload artifacts/release/*.whl", pipeline)
        manifest_script = (ROOT.parents[2] / ".buildkite/package_sandbox_manifest.sh").read_text()
        self.assertIn("manifest create", manifest_script)
        self.assertIn("manifest push", manifest_script)
        self.assertIn("yr-controlplane", manifest_script)
        self.assertIn("yr-node", manifest_script)
        self.assertIn("yr-runtime", manifest_script)
        self.assertIn("amd64 arm64", manifest_script)
        self.assertIn(':${IMAGE_TAG}-${arch}', manifest_script)
        self.assertEqual(
            yuanrong_ci_values["agentStack"]["targetKubeconfig"]["secretName"],
            "sandbox-target-kubeconfig",
        )
        self.assertEqual(
            yuanrong_ci_values["agentStack"]["targetKubeconfig"]["mountPath"],
            "/var/run/yr-k8s/target",
        )
        self.assertEqual(
            yuanrong_ci_values["secrets"]["targetKubeconfig"]["secretName"],
            "sandbox-target-kubeconfig",
        )
        self.assertIn("testPypiCredentials", yuanrong_ci_values["secrets"])
        self.assertIn("secrets.targetKubeconfig.create", (ROOT.parents[2] / "deploy/helm/yuanrong-ci/README.md").read_text())
        self.assertIn("secrets.testPypiCredentials.create", (ROOT.parents[2] / "deploy/helm/yuanrong-ci/README.md").read_text())
        self.assertIn("/var/run/yr-k8s/target/kubeconfig", str(yuanrong_ci_values["agentStack"]["podSpecPatch"]))
        self.assertIn("sandbox-target-kubeconfig", str(agent_stack_values["config"]["pod-spec-patch"]))
        self.assertIn("/var/run/yr-k8s/target/kubeconfig", str(agent_stack_values["config"]["pod-spec-patch"]))
        self.assertIn("yr-runtime", (ROOT / "push-images-swr.sh").read_text())

    def test_pipeline_builds_sdk_matrix_and_manifest_archive(self):
        setup_py = (ROOT.parents[2] / "api/python/setup.py").read_text()
        pipeline = (ROOT.parents[2] / ".buildkite/pipeline.dynamic.yml").read_text()
        package_script = (ROOT.parents[2] / ".buildkite/package_sandbox_release.sh").read_text()
        package_upload_script = (ROOT.parents[2] / ".buildkite/upload_buildkite_packages.sh").read_text()
        smoke_script = (ROOT.parents[2] / ".buildkite/test_sandbox_k8s.sh").read_text()
        manifest_script = (ROOT.parents[2] / ".buildkite/package_sandbox_manifest.sh").read_text()
        sdk_build_script = (ROOT.parents[2] / ".buildkite/build_openyuanrong_sdk_wheels.sh").read_text()
        macos_tools = (ROOT.parents[2] / "scripts/ensure-macos-build-tools.sh").read_text()

        self.assertIn('python_requires=">=3.9,<3.13"', setup_py)
        self.assertIn("Programming Language :: Python :: 3.12", setup_py)
        self.assertIn('SDK_PYTHON_VERSIONS="${SDK_PYTHON_VERSIONS:-python3.9 python3.10 python3.11 python3.12}"', pipeline)
        self.assertIn('SANDBOX_RUNTIME_IMAGE_PYTHON_VERSIONS="${SANDBOX_RUNTIME_IMAGE_PYTHON_VERSIONS:-${SDK_PYTHON_VERSIONS}}"', pipeline)
        self.assertIn("build_openyuanrong_sdk_wheels.sh output", pipeline)
        sdk_suffixes = ("cp39", "cp310", "cp311", "cp312")
        sdk_platforms = ("amd64", "arm64", "macos-arm64")
        sdk_keys = [f"build-sdk-{platform}-{suffix}" for platform in sdk_platforms for suffix in sdk_suffixes]
        self.assertIn('key: "build-sdk-amd64-${SDK_SUFFIX}"', pipeline)
        self.assertIn('key: "build-sdk-arm64-${SDK_SUFFIX}"', pipeline)
        self.assertIn('key: "build-sdk-macos-arm64-${SDK_SUFFIX}"', pipeline)
        self.assertIn('sdk_python_suffix()', pipeline)
        for sdk_key in sdk_keys:
            self.assertIn(sdk_key, manifest_script)
        self.assertIn('local key="publish-runtime-${image_arch}-${sdk_suffix}"', pipeline)
        self.assertIn('publish-runtime-amd64-${SDK_SUFFIX}', pipeline)
        self.assertIn('publish-runtime-arm64-${SDK_SUFFIX}', pipeline)
        self.assertIn('SANDBOX_AMD64_SDK_STEP="build-sdk-amd64-cp39"', pipeline)
        self.assertIn('SANDBOX_ARM64_SDK_STEP="build-sdk-arm64-cp39"', pipeline)
        self.assertIn('SANDBOX_SDK_STEP_KEY: "${SANDBOX_AMD64_SDK_STEP}"', pipeline)
        self.assertIn('SANDBOX_SDK_STEP_KEY: "${SANDBOX_ARM64_SDK_STEP}"', pipeline)
        self.assertIn('export SDK_PYTHON_VERSIONS="${SDK_PYTHON_VERSION}"', pipeline)
        self.assertIn('SANDBOX_MANIFEST_SDK_DEPENDS', pipeline)
        self.assertIn('SANDBOX_MANIFEST_RUNTIME_DEPENDS', pipeline)
        self.assertIn('emit_sandbox_runtime_image()', pipeline)
        self.assertIn('YR_K8S_RUNTIME_ONLY: "1"', pipeline)
        self.assertIn('YR_K8S_IMAGE_TAG_SUFFIX: "-${image_arch}-${sdk_suffix}"', pipeline)
        self.assertIn('YR_K8S_IMAGE_SDK_WHEEL_PATTERN: "openyuanrong_sdk*-${sdk_suffix}-*.whl"', pipeline)
        self.assertIn('SANDBOX_RUNTIME_IMAGE_STEPS: "${SANDBOX_RUNTIME_IMAGE_STEPS}"', pipeline)
        self.assertIn('BAZEL_OUTPUT_USER_ROOT="${output_root}"', sdk_build_script)
        self.assertIn('BAZEL_OUTPUT_BASE="${output_root}/output"', sdk_build_script)
        self.assertIn('bash "${ROOT_DIR}/build.sh" -p "${python_bin}" -v "${BUILD_VERSION}" -j "${SDK_BAZEL_JOBS}"', sdk_build_script)
        self.assertNotIn("bazel \"${bazel_options[@]}\"", sdk_build_script)
        self.assertIn('SDK_BAZEL_JOBS="${SDK_BAZEL_JOBS:-8}"', sdk_build_script)
        self.assertIn('SDK_BAZEL_BUILD_ROOT="${SDK_BAZEL_BUILD_ROOT:-${ROOT_DIR}/build/sdk-${BUILDKITE_JOB_ID:-local}}"', sdk_build_script)
        build_sh = (ROOT.parents[2] / "build.sh").read_text()
        self.assertIn('BUILD_BASE="${BAZEL_OUTPUT_USER_ROOT:-${BASE_DIR}/build}"', build_sh)
        self.assertIn('OUTPUT_BASE="${BAZEL_OUTPUT_BASE:-${BUILD_BASE}/output}"', build_sh)
        self.assertIn('BAZEL_OPTIONS_ENV="$BAZEL_OPTIONS_ENV --jobs=${OPTARG} "', build_sh)
        self.assertIn("python3.9 python3.10 python3.11 python3.12", pipeline)
        self.assertNotIn("SETUP_TYPE=sdk PYTHON_RUNTIME_VERSION=python3.11 python3 setup.py bdist_wheel", pipeline)
        self.assertNotIn('key: "build-macos-arm64"', pipeline)
        self.assertIn("scripts/ensure-macos-build-tools.sh", pipeline)
        self.assertIn("unset REMOTE_CACHE", pipeline)
        self.assertIn('build-sdk-macos-arm64-cp39', manifest_script)
        self.assertIn('artifact download "artifacts/openyuanrong-sdk/*"', manifest_script)
        self.assertIn("build-sdk-amd64-cp312", manifest_script)
        self.assertIn("build-sdk-arm64-cp312", manifest_script)
        self.assertIn("build-sdk-macos-arm64-cp312", manifest_script)
        self.assertIn('artifact download "artifacts/release/*"', manifest_script)
        self.assertIn("linux-amd64", manifest_script)
        self.assertIn("linux-amd64-sdk", manifest_script)
        self.assertIn("linux-arm64", manifest_script)
        self.assertIn("linux-arm64-sdk", manifest_script)
        self.assertIn("macos-arm64-sdk", manifest_script)
        self.assertIn("archive/index.html", manifest_script)
        self.assertIn("write_artifact_archive_html", manifest_script)
        self.assertIn('YR_K8S_IMAGE_SDK_WHEEL_PATTERN:-openyuanrong_sdk*-cp39-*.whl', package_script)
        self.assertIn('RUNTIME_ONLY="${YR_K8S_RUNTIME_ONLY:-0}"', package_script)
        self.assertIn('write_runtime_metadata', package_script)
        self.assertIn('if ! is_enabled "${RUNTIME_ONLY}"; then', package_script)
        self.assertIn('RUNTIME_ONLY="${YR_K8S_RUNTIME_ONLY:-0}"', (ROOT / "build-images.sh").read_text())
        self.assertIn('cp312)', (ROOT / "build-images.sh").read_text())
        self.assertIn('local_images=(yr-runtime)', (ROOT / "push-images-swr.sh").read_text())
        self.assertIn('RUNTIME_IMAGE_STEPS="${SANDBOX_RUNTIME_IMAGE_STEPS:-}"', manifest_script)
        self.assertIn('DEFAULT_RUNTIME_SDK_SUFFIX="${YR_K8S_DEFAULT_RUNTIME_SDK_SUFFIX:-cp310}"', manifest_script)
        self.assertIn('RUNTIME_IMAGE_TAG="${YR_K8S_RUNTIME_IMAGE_TAG:-${IMAGE_TAG}-${DEFAULT_RUNTIME_SDK_SUFFIX}}"', manifest_script)
        self.assertIn('create_manifest "yr-runtime" "${IMAGE_TAG}-${sdk_suffix}" "-${sdk_suffix}"', manifest_script)
        self.assertIn("Runtime image tags", manifest_script)
        self.assertIn("https://api.buildkite.com/v2/packages/organizations/openyuanrong/registries/openyuanrong/packages", package_upload_script)
        self.assertIn('PACKAGE_UPLOAD_TOKEN="${BUILDKITE_PACKAGE_UPLOAD_TOKEN:-${BUILDKITE_PACKAGES_TOKEN:-}}"', package_upload_script)
        self.assertIn('-F "file=@${file}"', package_upload_script)
        self.assertIn("bash .buildkite/upload_buildkite_packages.sh artifacts/release/*.whl", pipeline)
        self.assertIn("bash .buildkite/upload_buildkite_packages.sh artifacts/openyuanrong-sdk/*.whl", pipeline)
        self.assertIn("buildkite-package-credentials", pipeline)
        self.assertIn("key: api-token", pipeline)
        self.assertIn('YR_K8S_SMOKE_SDK_WHEEL_PATTERN:-openyuanrong_sdk*-cp39-*.whl', smoke_script)
        self.assertIn('*-cp312-*) python_minor="3.12" ;;', smoke_script)
        self.assertIn("python@3.12", macos_tools)

    def test_push_images_falls_back_when_platform_push_is_unsupported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            docker_log = pathlib.Path(tmpdir) / "docker.log"
            fake_docker = pathlib.Path(tmpdir) / "docker"
            fake_docker.write_text(
                "#!/usr/bin/env bash\n"
                "echo \"$*\" >> \"${DOCKER_LOG}\"\n"
                "if [ \"$1\" = push ] && [ \"${2:-}\" = --help ]; then\n"
                "  echo 'Usage: docker push NAME[:TAG]'\n"
                "  exit 0\n"
                "fi\n"
                "if [ \"$1\" = image ] && [ \"${2:-}\" = inspect ]; then exit 0; fi\n"
                "if [ \"$1\" = push ] && [ \"${2:-}\" = --platform ]; then exit 42; fi\n"
                "exit 0\n"
            )
            fake_docker.chmod(0o755)
            result = subprocess.run(
                ["bash", str(ROOT / "push-images-swr.sh")],
                cwd=ROOT.parents[2],
                check=True,
                capture_output=True,
                text=True,
                env={
                    "PATH": f"{tmpdir}:/usr/bin:/bin",
                    "DOCKER_BIN": str(fake_docker),
                    "DOCKER_LOG": str(docker_log),
                    "YR_K8S_REGISTRY_REPO": "registry.example.com/openyuanrong",
                    "YR_K8S_IMAGE_TAG": "test-tag",
                    "YR_K8S_IMAGE_PLATFORM": "linux/arm64",
                    "YR_K8S_IMAGE_CACHE": "1",
                    "YR_K8S_IMAGE_CACHE_TAG": "cache-arm64",
                },
            )

            log_text = docker_log.read_text()
            self.assertNotIn("push --platform", log_text)
            self.assertIn("push registry.example.com/openyuanrong/yr-base:test-tag", log_text)
            self.assertIn("push registry.example.com/openyuanrong/yr-base:cache-arm64", log_text)
            self.assertIn("without platform flag", result.stderr)


if __name__ == "__main__":
    unittest.main()
