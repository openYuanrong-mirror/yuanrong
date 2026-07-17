# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import pathlib
import re
import stat
import subprocess
import tempfile
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]
HELM_BIN = pathlib.Path(os.environ.get("HELM_BIN", "/home/wyc/.local/bin/helm"))
PYTHON_BIN = pathlib.Path(os.environ.get("PYTHON_BIN", "/usr/bin/python3"))
BASH_BIN = pathlib.Path(os.environ.get("BASH_BIN", "/bin/bash"))
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


def emit_dynamic_pipeline(**overrides: str) -> dict:
    env = dict(os.environ)
    env.update(overrides)
    result = subprocess.run(
        [str(BASH_BIN), ".buildkite/pipeline.dynamic.yml"],
        cwd=ROOT.parents[2],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return yaml.safe_load(result.stdout)


def flatten_pipeline_steps(document: dict) -> list[dict]:
    result = []
    for step in document["steps"]:
        result.extend(step.get("steps", [step]))
    return result


def pipeline_step_container(step: dict) -> dict:
    return step["plugins"][0]["kubernetes"]["podSpec"]["containers"][0]


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


def expected_runtime_image(values: dict, suffix: str) -> str:
    image = dict(values["global"]["images"]["runtime"])
    image.update(values["global"]["runtimeImages"].get(suffix, {}))
    registry = image.get("registry", values["global"]["imageRegistry"]).rstrip("/")
    return f"{registry}/{image['repository']}:{image['tag']}"


def expected_etcd_addr(values: dict) -> str:
    if values["global"]["externalEtcd"]["addrList"]:
        return values["global"]["externalEtcd"]["addrList"]
    return f"yr-etcd.{NAMESPACE}.svc.cluster.local:{values['etcd']['service']['port']}"


class YrK8sLayoutTests(unittest.TestCase):
    def test_traefik_uses_master_http_provider_on_web_entrypoint(self):
        manifests = render_chart()
        master = find_manifest(manifests, "StatefulSet", "yr-master")
        traefik = find_manifest(manifests, "Deployment", "yr-traefik")
        service = find_manifest(manifests, "Service", "yr-traefik")
        static_config = find_manifest(manifests, "ConfigMap", "yr-traefik-configmap")["data"]["traefik.yaml"]
        dynamic_config = find_manifest(manifests, "ConfigMap", "yr-traefik-dynamic")["data"]["config.yml"]

        master_container = find_container(master, "master")
        self.assertEqual(find_env(master_container, "YR_ENABLE_TRAEFIK_PROVIDER"), "true")
        self.assertEqual(find_env(master_container, "YR_TRAEFIK_HTTP_ENTRY_POINT"), "web")
        self.assertIn(
            "http://yr-master-access:22770/global-scheduler/traefik/config",
            static_config,
        )
        self.assertIn('pollInterval: "5s"', static_config)
        self.assertIn('pollTimeout: "5s"', static_config)
        self.assertNotIn("etcd:", static_config)
        self.assertNotIn("router:", static_config)
        self.assertNotIn("tunnel-router", dynamic_config)
        self.assertNotIn("sandbox-router", dynamic_config)
        self.assertEqual([p["name"] for p in find_container(traefik, "traefik")["ports"]], ["web"])
        self.assertEqual([p["name"] for p in service["spec"]["ports"]], ["web"])

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
                "k8s/values.buildkite-smoke.yaml",
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
        test_pypi_upload_script = (ROOT.parents[2] / ".buildkite/upload_test_pypi_wheels.sh").read_text()
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
        self.assertIn('buildkite-agent meta-data get "obs-urls.${BUILD_STEP_KEY}"', package_script)
        self.assertIn('buildkite-agent meta-data get "obs-urls.${SDK_STEP_KEY}"', package_script)
        self.assertIn(".buildkite/download_obs_artifacts.py", package_script)
        self.assertIn('--pattern "openyuanrong-*.whl"', package_script)
        self.assertIn('--pattern "${IMAGE_SDK_WHEEL_PATTERN}"', package_script)
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
        self.assertEqual(
            sorted(values["global"]["runtimeImages"].keys()),
            ["cp310", "cp311", "cp312", "cp313", "cp314", "cp39"],
        )
        self.assertIn("py314", values["global"]["services"]["servicesYaml"])
        self.assertIn("runtime: python3.14", values["global"]["services"]["servicesYaml"])
        self.assertIn('"suffix" "cp314"', values["global"]["services"]["servicesYaml"])
        self.assertIn("yr-k8s.runtimeImage", values["global"]["services"]["servicesYaml"])
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
        services_yaml = services_cm["data"]["services.yaml"]
        self.assertIn(expected_image(values, "runtime"), services_yaml)
        functions = yaml.safe_load(services_yaml)[0]["functions"]
        self.assertEqual(functions["default"]["runtime"], "python3.11")
        self.assertNotIn("rootfs", functions["default"])
        self.assertEqual(functions["py39"]["runtime"], "python3.9")
        self.assertNotIn("rootfs", functions["py39"])
        self.assertIn("py310", functions)
        self.assertEqual(functions["py310"]["runtime"], "python3.10")
        self.assertEqual(functions["py310"]["rootfs"]["imageurl"], expected_runtime_image(values, "cp310"))
        self.assertEqual(functions["py310"]["bootstrap"]["entrypoint"], "python -m yr.cli.scripts runtime_main")
        self.assertIn("py312", functions)
        self.assertEqual(functions["py312"]["runtime"], "python3.12")
        self.assertEqual(functions["py312"]["rootfs"]["imageurl"], expected_runtime_image(values, "cp312"))
        self.assertEqual(functions["py312"]["bootstrap"]["entrypoint"], "python -m yr.cli.scripts runtime_main")
        self.assertEqual(functions["py314"]["runtime"], "python3.14")
        self.assertEqual(functions["py314"]["rootfs"]["imageurl"], expected_runtime_image(values, "cp314"))
        self.assertEqual(functions["py314"]["bootstrap"]["entrypoint"], "python -m yr.cli.scripts runtime_main")

        master_container = find_container(master_sts, "master")
        controlplane_image = expected_image(values, "controlplane")
        for manifest in [master_sts, frontend_dep, node_ds]:
            annotations = manifest["spec"]["template"]["metadata"]["annotations"]
            self.assertRegex(annotations["checksum/components"], r"^[0-9a-f]{64}$")
            self.assertRegex(annotations["checksum/services"], r"^[0-9a-f]{64}$")

        self.assertEqual(master_container["image"], controlplane_image)
        self.assertEqual(master_container["command"], ["/usr/local/bin/start-master.sh"])
        self.assertEqual(find_env(master_container, "YR_ETCD_ADDR_LIST"), etcd_addr)
        self.assertEqual(find_env(master_container, "YR_ENABLE_TRAEFIK_PROVIDER"), "true")
        self.assertEqual(find_env(master_container, "YR_TRAEFIK_HTTP_ENTRY_POINT"), "web")
        master_mounts = {m["mountPath"] for m in master_container.get("volumeMounts", [])}
        self.assertIn(values["debug"]["sidecar"]["sessionDir"], master_mounts)

        frontend_container = find_container(frontend_dep, "frontend")
        self.assertEqual(frontend_container["image"], controlplane_image)
        self.assertEqual(frontend_container["command"], ["/usr/local/bin/start-frontend.sh"])
        self.assertEqual(frontend_container.get("args"), [])
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
        provider_endpoint = f"http://{master_access_name}:22770/global-scheduler/traefik/config"
        self.assertIn(provider_endpoint, traefik_text)
        self.assertIn('pollInterval: "5s"', traefik_text)
        self.assertIn('pollTimeout: "5s"', traefik_text)
        self.assertNotIn("etcd:", traefik_text)
        self.assertIn("/etc/traefik/dynamic", traefik_text)
        self.assertIn(frontend_name, traefik_dynamic_text)
        self.assertIn("/api/sandbox", traefik_dynamic_text)
        self.assertIn("/serverless/v1/componentshealth", traefik_dynamic_text)
        self.assertIn("/invocations", traefik_dynamic_text)
        self.assertIn("direct-router", traefik_dynamic_text)
        self.assertIn("PathPrefix(`/direct/`) || Path(`/direct`)", traefik_dynamic_text)
        self.assertNotIn("tunnel-router", traefik_dynamic_text)
        self.assertNotIn("sandbox-router", traefik_dynamic_text)
        self.assertIn("service: frontend", traefik_dynamic_text)
        self.assertNotIn("direct-strip", traefik_dynamic_text)
        self.assertEqual(find_container(traefik_dep, "traefik")["image"], expected_image(values, "traefik"))
        self.assertEqual(traefik_svc["spec"]["ports"][0]["port"], values["traefik"]["service"]["port"])
        self.assertEqual(len(traefik_svc["spec"]["ports"]), 1)
        self.assertEqual([p["name"] for p in find_container(traefik_dep, "traefik")["ports"]], ["web"])

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

    def test_buildkite_smoke_overlay_uses_cluster_ip_services(self):
        overlay = ROOT / "k8s/values.buildkite-smoke.yaml"
        self.assertTrue(overlay.is_file())
        overlay_values = load_yaml_file(overlay)
        self.assertTrue(overlay_values["frontend"]["enableEvent"])

        for component in ["traefik", "frontend"]:
            with self.subTest(component=component):
                service = overlay_values[component]["service"]
                self.assertEqual(service["type"], "ClusterIP")
                self.assertIsNone(service["annotations"])

        manifests = render_chart("-f", str(ROOT / "k8s/values.local.yaml"), "-f", str(overlay))
        for service_name in ["yr-traefik", "yr-frontend"]:
            with self.subTest(service=service_name):
                service = find_manifest(manifests, "Service", service_name)
                self.assertEqual(service["spec"]["type"], "ClusterIP")
                self.assertNotIn("annotations", service["metadata"])

    def test_deploy_migrates_legacy_load_balancer_services(self):
        deploy_script = (ROOT / "deploy.sh").read_text()

        self.assertIn("YR_K8S_EXTRA_VALUES_FILE", deploy_script)
        self.assertIn("delete_legacy_load_balancer_services", deploy_script)
        self.assertIn('app.kubernetes.io/component="${component}"', deploy_script)
        self.assertIn("delete_legacy_load_balancer_service traefik Traefik", deploy_script)
        self.assertIn("delete_legacy_load_balancer_service frontend Frontend", deploy_script)
        self.assertIn("jsonpath={.spec.type}", deploy_script)
        self.assertIn("Deleting legacy %s LoadBalancer service", deploy_script)
        self.assertIn("delete_legacy_load_balancer_services", deploy_script.split("create_or_update_pull_secret", 1)[1])

    def test_buildkite_smoke_uses_port_forward(self):
        deploy_script = (ROOT.parents[2] / ".buildkite/test_sandbox_k8s.sh").read_text()

        self.assertIn("values.buildkite-smoke.yaml", deploy_script)
        self.assertIn("YR_K8S_EXTRA_VALUES_FILE", deploy_script)
        self.assertIn("start_traefik_port_forward", deploy_script)
        port_forward_cmd = '"${KUBECTL_BIN}" --kubeconfig "${KUBECONFIG_PATH}" -n "${NAMESPACE}" port-forward'
        self.assertIn(port_forward_cmd, deploy_script)
        self.assertIn("TRAEFIK_WEB_ADDRESS", deploy_script)
        self.assertIn("TRAEFIK_ROUTER_ADDRESS", deploy_script)
        self.assertIn('TRAEFIK_ROUTER_PORT="${YR_K8S_TRAEFIK_ROUTER_PORT:-8080}"', deploy_script)
        self.assertIn('probe_sandbox_ready "${smoke_server_address}"', deploy_script)
        self.assertIn('run_idle_timeout_e2e "${smoke_server_address}"', deploy_script)
        self.assertIn('run_smoke "${smoke_server_address}"', deploy_script)
        self.assertIn('run_rrt_direct_e2e "${smoke_server_address}" "${router_address}"', deploy_script)
        self.assertNotIn('$(wait_for_traefik_address', deploy_script.split("bash deploy/sandbox/k8s/deploy.sh", 1)[1])
        token_command = re.search(r'yr_token="\$\("\$\{py\}" -c \'([^\']+)\'\)"', deploy_script)
        self.assertIsNotNone(token_command)
        token = subprocess.check_output([str(PYTHON_BIN), "-c", token_command.group(1)], text=True).strip()
        self.assertEqual(3, len(token.split(".")))

    def test_buildkite_can_emit_k8s_test_only_pipeline(self):
        env = dict(os.environ)
        env["ENABLE_SANDBOX_K8S_TEST_ONLY"] = "true"
        result = subprocess.run(
            [str(BASH_BIN), ".buildkite/pipeline.dynamic.yml"],
            cwd=ROOT.parents[2],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        pipeline = result.stdout

        self.assertIn('key: "test-k8s"', pipeline)
        self.assertIn("test_sandbox_k8s.sh", pipeline)
        self.assertNotIn("Build X86", pipeline)
        self.assertNotIn("Build Image", pipeline)
        self.assertNotIn("publish-sandbox-release", pipeline)
        self.assertNotIn('depends_on:', pipeline)

    def test_pipeline_deploys_published_sandbox_release_to_target_k8s(self):
        bootstrap_pipeline = (ROOT.parents[2] / ".buildkite/pipeline.yml").read_text()
        pipeline = (ROOT.parents[2] / ".buildkite/pipeline.dynamic.yml").read_text()
        test_pypi_upload_script = (ROOT.parents[2] / ".buildkite/upload_test_pypi_wheels.sh").read_text()
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
        self.assertIn('- \\"${SANDBOX_FINAL_PACKAGE_STEP}\\"', pipeline)
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
        self.assertIn("frontend_deployment()", deploy_script_k8s)
        self.assertIn("restart_frontend_after_master_ready", deploy_script_k8s)
        self.assertIn("rollout restart", deploy_script_k8s)
        self.assertRegex(
            deploy_script_k8s,
            r"delete_legacy_load_balancer_services\s+helm_deploy\s+patch_workloads_with_pull_secret\s+"
            r"wait_for_rollout\s+restart_frontend_after_master_ready\s+prepull_runtime_image",
        )
        self.assertIn("prepull_runtime_image", deploy_script_k8s)
        self.assertIn('RUNTIME_IMAGE_TAG_CP39="${YR_K8S_RUNTIME_IMAGE_TAG_CP39:-${IMAGE_TAG}-cp39}"', deploy_script_k8s)
        self.assertIn('--set global.runtimeImages.cp39.tag="${RUNTIME_IMAGE_TAG_CP39}"', deploy_script_k8s)
        self.assertIn('--set global.runtimeImages.cp312.tag="${RUNTIME_IMAGE_TAG_CP312}"', deploy_script_k8s)
        self.assertIn('--set global.runtimeImages.cp314.tag="${RUNTIME_IMAGE_TAG_CP314}"', deploy_script_k8s)
        self.assertIn("cp39 cp310 cp311 cp312 cp313 cp314", deploy_script_k8s)
        self.assertIn('cp314) tag="${RUNTIME_IMAGE_TAG_CP314}"', deploy_script_k8s)
        self.assertIn("docker pull", deploy_script_k8s)
        self.assertIn("run_off_cluster_test.sh", deploy_script)
        self.assertIn('buildkite-agent meta-data get "sandbox-release.${PACKAGE_STEP_KEY}"', deploy_script)
        self.assertIn('buildkite-agent meta-data get "obs-urls.${BUILD_STEP_KEY}"', deploy_script)
        self.assertIn('buildkite-agent meta-data get "obs-urls.${SDK_STEP_KEY}"', deploy_script)
        self.assertIn(".buildkite/download_obs_artifacts.py", deploy_script)
        self.assertIn('--pattern "openyuanrong-*.whl"', deploy_script)
        self.assertIn('--pattern "${SMOKE_SDK_WHEEL_PATTERN}"', deploy_script)
        self.assertNotIn('artifact download "artifacts/release/*"', deploy_script)
        self.assertIn("runtime_image_tag", deploy_script)
        self.assertIn("YR_K8S_RUNTIME_IMAGE_TAG_CP39", deploy_script)
        self.assertIn("YR_K8S_SMOKE_PIP_INDEX_URL", deploy_script)
        self.assertIn("YR_OFF_CLUSTER_USE_UV_VENV=false", deploy_script)
        self.assertIn("--no-uv-venv -p", deploy_script)
        self.assertIn("-m smoke", deploy_script)
        self.assertIn("YR_OFF_CLUSTER_TEST_TIMEOUT", deploy_script)
        self.assertIn('UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-300}"', deploy_script)
        self.assertIn("cp output/openyuanrong-*.whl artifacts/release/", pipeline)
        self.assertNotIn("cp datasystem/output/*.whl artifacts/release/", pipeline)
        self.assertNotIn("cp datasystem/output/sdk/*.whl artifacts/release/", pipeline)
        self.assertNotIn("cp functionsystem/output/*.whl artifacts/release/", pipeline)
        self.assertIn("TEST_PYPI_API_TOKEN", pipeline)
        self.assertIn("test-pypi-credentials", pipeline)
        self.assertIn("PYPI_API_TOKEN", pipeline)
        self.assertIn("pypi-credentials", pipeline)
        self.assertIn("openyuanrong_sdk-*.whl", pipeline)
        self.assertIn("https://test.pypi.org/legacy/", test_pypi_upload_script)
        self.assertIn("https://upload.pypi.org/legacy/", test_pypi_upload_script)
        self.assertNotIn("twine upload artifacts/release/*.whl", pipeline)
        self.assertTrue(yuanrong_ci_values["gitcodeWebhookRelay"]["buildkite"]["triggerTagPush"])
        self.assertIn("[0-9]*", yuanrong_ci_values["gitcodeWebhookRelay"]["filters"]["tagPatterns"])
        self.assertIn("v[0-9]*", yuanrong_ci_values["gitcodeWebhookRelay"]["filters"]["tagPatterns"])
        manifest_script = (ROOT.parents[2] / ".buildkite/package_sandbox_manifest.sh").read_text()
        self.assertIn("manifest create", manifest_script)
        self.assertIn("manifest push", manifest_script)
        self.assertIn("yr-controlplane", manifest_script)
        self.assertIn("yr-node", manifest_script)
        self.assertIn("yr-runtime", manifest_script)
        self.assertIn('"runtime_image_tag": "${RUNTIME_IMAGE_TAG}"', manifest_script)
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
        self.assertIn("pypiCredentials", yuanrong_ci_values["secrets"])
        self.assertIn("secrets.targetKubeconfig.create", (ROOT.parents[2] / "deploy/helm/yuanrong-ci/README.md").read_text())
        self.assertIn("secrets.testPypiCredentials.create", (ROOT.parents[2] / "deploy/helm/yuanrong-ci/README.md").read_text())
        self.assertIn("secrets.pypiCredentials.create", (ROOT.parents[2] / "deploy/helm/yuanrong-ci/README.md").read_text())
        self.assertIn("/var/run/yr-k8s/target/kubeconfig", str(yuanrong_ci_values["agentStack"]["podSpecPatch"]))
        self.assertIn("sandbox-target-kubeconfig", str(agent_stack_values["config"]["pod-spec-patch"]))
        self.assertIn("/var/run/yr-k8s/target/kubeconfig", str(agent_stack_values["config"]["pod-spec-patch"]))
        self.assertIn("yr-runtime", (ROOT / "push-images-swr.sh").read_text())

    def test_python314_package_and_cli_contract(self):
        repo = ROOT.parents[2]
        setup_py = (repo / "api/python/setup.py").read_text()
        requirements = (repo / "api/python/requirements.txt").read_text()
        rrt_setup = (repo / "api/python-rrt/setup.py").read_text()
        cli = (repo / "api/python/yr/cli/scripts.py").read_text()
        docs = (repo / "docs/features/yrcli.md").read_text()
        self.assertIn('python_requires=">=3.9,<3.15"', setup_py)
        self.assertIn("Programming Language :: Python :: 3.14", setup_py)
        for dependency_file in (setup_py, requirements):
            self.assertIn('protobuf==4.25.5; python_version < "3.14"', dependency_file)
            self.assertIn('protobuf>=7.35.1,<8; python_version >= "3.14"', dependency_file)
        self.assertIn('python_requires=">=3.9,<3.15"', rrt_setup)
        self.assertIn('"python3.14"', cli)
        self.assertIn("python3.14", docs)

    def test_process_default_services_include_python313_and_python314(self):
        repo = ROOT.parents[2]
        for relative_path in (
            "deploy/process/services.yaml",
            "api/python/yr/cli/services.yaml",
        ):
            with self.subTest(path=relative_path):
                functions = load_yaml_file(repo / relative_path)[0]["functions"]
                self.assertEqual(functions["py313"]["runtime"], "python3.13")
                self.assertEqual(functions["py314"]["runtime"], "python3.14")

    def test_python314_toolchain_contract(self):
        repo = ROOT.parents[2]
        check_tools = (repo / "check_tools.sh").read_text()
        build = (repo / "build.sh").read_text()
        install_tools = (repo / "install_tools.sh").read_text()
        openeuler_dockerfiles = {
            relative: (repo / relative).read_text()
            for relative in (
                "ci/openeuler/Dockerfile.x86_64",
                "ci/openeuler/Dockerfile.aarch64",
            )
        }
        ubuntu = (repo / "ci/ubuntu/Dockerfile.ubuntu2004").read_text()
        compose = (repo / "ci/ubuntu/docker-compose.yml").read_text()
        macos = (repo / "scripts/ensure-macos-build-tools.sh").read_text()
        overlay = (repo / "ci/ubuntu/Dockerfile.python314-overlay").read_text()

        self.assertIn("python3.14", check_tools)
        self.assertIn("Python 3.14", check_tools)
        self.assertIn("python3.13", check_tools)
        self.assertIn("/opt/buildtools/python3.14/lib", build)
        self.assertIn('"python3.14"', build)
        self.assertIn('"python3.13"', build)

        optional_archive = 'python-3.14.6-linux-${PKG_ARCH}.tar.gz'
        self.assertIn(f'if [[ -f "$PKG_DIR/{optional_archive}" ]]', install_tools)
        self.assertIn(f'sudo tar -xzf "$PKG_DIR/{optional_archive}" -C /', install_tools)
        required_packages = re.search(r"REQUIRED_PKGS=\((.*?)\n\)", install_tools, re.S)
        self.assertIsNotNone(required_packages)
        self.assertNotIn("python-3.14.6", required_packages.group(1))
        self.assertIn('python-3.13.0-linux-${PKG_ARCH}.tar.gz', install_tools)
        self.assertRegex(
            install_tools,
            r'for ver in .*?"3\.13"\s+"3\.14"; do\s+'
            r'python_bin="\$BUILD_TOOLS/python\$ver/bin/python\$ver"\s+'
            r'if \[\[ ! -x "\$python_bin" \]\]; then\s+continue\s+fi',
        )
        self.assertRegex(
            install_tools,
            r'for ver in .*?"3\.13"\s+"3\.14"; do\s+'
            r'python_lib="\$BUILD_TOOLS/python\$ver/lib"\s+'
            r'if \[\[ ! -d "\$python_lib" \]\]; then\s+continue\s+fi',
        )
        self.assertIn("PYTHON_PATH_3146=/opt/buildtools/python3.14", install_tools)

        openeuler_needles = (
            "https://mirrors.huaweicloud.com/python/3.14.6/Python-3.14.6.tgz",
            "./configure --prefix=/opt/buildtools/python3.14 --enable-shared --with-openssl=/usr",
            "ln -sf /opt/buildtools/python3.14/bin/python3.14 /usr/local/bin/python3.14",
            'echo "/opt/buildtools/python3.14/lib" > /etc/ld.so.conf.d/python3.14.conf',
            "PYTHON_PATH_3146=/opt/buildtools/python3.14",
            "pip3.14 install setuptools packaging wheel",
            "Python-3.13.2.tgz",
        )
        for relative, text in openeuler_dockerfiles.items():
            for needle in openeuler_needles:
                self.assertIn(needle, text, relative)

        self.assertRegex(ubuntu, r"for v in\s+.*?3\.13\.0\s+3\.14\.6; do")
        self.assertRegex(ubuntu, r"for v in\s+.*?3\.13\s+3\.14; do")
        self.assertIn("ENV PYTHON_PATH_3146=/opt/buildtools/python3.14", ubuntu)
        self.assertIn("/opt/buildtools/python3.14/bin", ubuntu)
        self.assertIn("/opt/buildtools/python3.14/lib", ubuntu)
        self.assertIn("3.13.0", ubuntu)
        self.assertIn("PYTHON_PATH_3146: /opt/buildtools/python3.14", compose)
        self.assertIn("/opt/buildtools/python3.14/bin", compose)
        self.assertIn("/opt/buildtools/python3.14/lib", compose)

        self.assertRegex(macos, r"for py in\s+python3\.14\s+python3\.13")
        self.assertRegex(macos, r"for py in\s+python@3\.14\s+python@3\.13")
        self.assertRegex(
            macos,
            r"python@3\.14\) echo [\s\S]*?python3\.14[\s\S]*?"
            r"python@3\.13\) echo [\s\S]*?python3\.13",
        )
        self.assertIn('PYTHON314_VERSION="${PYTHON314_VERSION:-3.14.6}"', macos)
        self.assertIn('HOME="${HOME:-$(dscl . -read', macos)
        self.assertIn('sudo -H -u "${brew_owner}" env', macos)
        self.assertIn('HOMEBREW_NO_AUTO_UPDATE=1', macos)
        self.assertIn(
            'installed_versions="$(brew_mutate list --versions "$formula" 2>/dev/null || true)"',
            macos,
        )
        self.assertIn('if [[ -n "${installed_versions}" ]]; then', macos)
        self.assertIn('prefix="$(brew_mutate --prefix "$formula")"', macos)
        self.assertNotRegex(
            macos,
            r'brew --prefix (?:openssl@3|readline|sqlite|xz)',
        )
        self.assertIn(
            'for py_version in ${SDK_PYTHON_VERSIONS:-python3.9 python3.10 '
            'python3.11 python3.12 python3.13 python3.14}; do',
            macos,
        )
        self.assertIn('--retry-all-errors', macos)
        self.assertIn('--continue-at -', macos)
        self.assertIn('--speed-limit 1024', macos)
        self.assertIn('--speed-time 60', macos)
        self.assertIn('Python-${PYTHON314_VERSION}.tgz', macos)
        self.assertIn("platform.python_version() == sys.argv[1]", macos)

        self.assertIn("ARG PYTHON_VERSION=3.14.6", overlay)
        self.assertIn("--prefix=/opt/buildtools/python3.14", overlay)
        self.assertIn("python3.14 --version", overlay)

    def test_pipeline_builds_sdk_matrix_and_manifest_archive(self):
        setup_py = (ROOT.parents[2] / "api/python/setup.py").read_text()
        pipeline = (ROOT.parents[2] / ".buildkite/pipeline.dynamic.yml").read_text()
        package_script = (ROOT.parents[2] / ".buildkite/package_sandbox_release.sh").read_text()
        package_upload_script = (ROOT.parents[2] / ".buildkite/upload_buildkite_packages.sh").read_text()
        obs_upload_script = (ROOT.parents[2] / ".buildkite/upload_obs_artifacts.sh").read_text()
        obs_download_script = (ROOT.parents[2] / ".buildkite/download_obs_artifacts.py").read_text()
        test_pypi_upload_script = (ROOT.parents[2] / ".buildkite/upload_test_pypi_wheels.sh").read_text()
        smoke_script = (ROOT.parents[2] / ".buildkite/test_sandbox_k8s.sh").read_text()
        manifest_script = (ROOT.parents[2] / ".buildkite/package_sandbox_manifest.sh").read_text()
        sdk_build_script = (ROOT.parents[2] / ".buildkite/build_openyuanrong_sdk_wheels.sh").read_text()
        sdk_thirdparty_cache_script = (
            ROOT.parents[2] / ".buildkite/prepare_sdk_thirdparty_cache.sh"
        ).read_text()
        macos_tools = (ROOT.parents[2] / "scripts/ensure-macos-build-tools.sh").read_text()

        self.assertIn('python_requires=">=3.9,<3.15"', setup_py)
        self.assertIn("Programming Language :: Python :: 3.14", setup_py)
        self.assertIn('SDK_PYTHON_VERSIONS="${SDK_PYTHON_VERSIONS:-python3.9 python3.10 python3.11 python3.12 python3.13 python3.14}"', pipeline)
        self.assertIn('SANDBOX_RUNTIME_IMAGE_PYTHON_VERSIONS="${SANDBOX_RUNTIME_IMAGE_PYTHON_VERSIONS:-${SDK_PYTHON_VERSIONS}}"', pipeline)
        self.assertIn('ENABLE_MACOS_SDK="${ENABLE_MACOS_SDK_OVERRIDE:-${ENABLE_MACOS_SDK:-true}}"', pipeline)
        self.assertIn('ENABLE_RUNTIME_X86="${ENABLE_RUNTIME_X86:-true}"', pipeline)
        self.assertIn('ENABLE_RUNTIME_ARM="${ENABLE_RUNTIME_ARM:-true}"', pipeline)
        self.assertIn('if [ -z "${ENABLE_TEST_PYPI_PUBLISH:-}" ]; then', pipeline)
        self.assertIn('ENABLE_TEST_PYPI_PUBLISH="${PUBLISH_TEST_PYPI:-true}"', pipeline)
        self.assertIn('if is_enabled "${ENABLE_RUNTIME_X86}"; then', pipeline)
        self.assertIn('if is_enabled "${ENABLE_RUNTIME_ARM}"; then', pipeline)
        self.assertIn("YR_RELEASE_TAG:-", pipeline)
        self.assertIn("BUILDKITE_TAG:-", pipeline)
        self.assertIn("TAG_BUILD_VERSION#refs/tags/", pipeline)
        self.assertIn("TAG_BUILD_VERSION#v", pipeline)
        self.assertIn("TAG_BUILD_VERSION:-0.7.0+", pipeline)
        self.assertIn("build_openyuanrong_sdk_wheels.sh output", pipeline)
        sdk_suffixes = ("cp39", "cp310", "cp311", "cp312", "cp313", "cp314")
        sdk_platforms = ("amd64", "arm64", "macos-arm64")
        sdk_keys = [f"build-sdk-{platform}-{suffix}" for platform in sdk_platforms for suffix in sdk_suffixes]
        self.assertIn('key: "build-sdk-amd64-${SDK_SUFFIX}"', pipeline)
        self.assertIn('key: "build-sdk-arm64-${SDK_SUFFIX}"', pipeline)
        self.assertIn('key: "build-sdk-macos-arm64-${SDK_SUFFIX}"', pipeline)
        arm_sdk_step = re.search(
            r'- label: ":snake: Build SDK arm \$\{SDK_SUFFIX\}".*?timeout_in_minutes: 120',
            pipeline,
            re.S,
        )
        self.assertIsNotNone(arm_sdk_step)
        self.assertIn("obs-credentials", arm_sdk_step.group(0))
        self.assertIn("OBS_ACCESS_KEY_ID", arm_sdk_step.group(0))
        self.assertIn("OBS_SECRET_ACCESS_KEY", arm_sdk_step.group(0))
        self.assertIn('sdk_python_suffix()', pipeline)
        self.assertIn("python3.14) printf 'cp314'", pipeline)
        for sdk_key in sdk_keys:
            self.assertIn(sdk_key, manifest_script)
        self.assertIn("build-sdk-amd64-cp314", manifest_script)
        self.assertIn("build-sdk-arm64-cp314", manifest_script)
        self.assertIn("build-sdk-macos-arm64-cp314", manifest_script)
        self.assertIn('local key="publish-runtime-${image_arch}-${sdk_suffix}"', pipeline)
        self.assertIn('publish-runtime-amd64-${SDK_SUFFIX}', pipeline)
        self.assertIn('publish-runtime-arm64-${SDK_SUFFIX}', pipeline)
        self.assertIn(
            'SANDBOX_AMD64_SDK_STEP="build-sdk-amd64-${SANDBOX_AMD64_SDK_SUFFIX}"', pipeline
        )
        self.assertIn(
            'SANDBOX_ARM64_SDK_STEP="build-sdk-arm64-${SANDBOX_ARM64_SDK_SUFFIX}"', pipeline
        )
        self.assertIn('SANDBOX_SDK_STEP_KEY: "${SANDBOX_AMD64_SDK_STEP}"', pipeline)
        self.assertIn('SANDBOX_SDK_STEP_KEY: "${SANDBOX_ARM64_SDK_STEP}"', pipeline)
        self.assertIn('export SDK_PYTHON_VERSIONS="${SDK_PYTHON_VERSION}"', pipeline)
        self.assertIn("import packaging, setuptools, wheel", sdk_build_script)
        self.assertIn("import wheel.bdist_wheel", sdk_build_script)
        self.assertIn("--upgrade", sdk_build_script)
        self.assertIn("packaging setuptools wheel", sdk_build_script)
        self.assertIn(".cache/openyuanrong/python/3.14.6", sdk_build_script)
        self.assertIn('SANDBOX_MANIFEST_SDK_DEPENDS', pipeline)
        self.assertIn('SANDBOX_MANIFEST_RUNTIME_DEPENDS', pipeline)
        self.assertIn('SANDBOX_TEST_PYPI_DEPENDS', pipeline)
        self.assertIn('SANDBOX_SDK_STEPS', pipeline)
        self.assertIn('emit_sandbox_runtime_image()', pipeline)
        self.assertIn('key: "publish-wheels-testpypi"', pipeline)
        self.assertIn('if is_enabled "${ENABLE_TEST_PYPI_PUBLISH}"; then', pipeline)
        self.assertIn("bash .buildkite/upload_test_pypi_wheels.sh artifacts/test-pypi-wheels", pipeline)
        self.assertIn('YR_K8S_RUNTIME_ONLY: "1"', pipeline)
        self.assertIn('YR_K8S_IMAGE_TAG_SUFFIX: "-${image_arch}-${sdk_suffix}"', pipeline)
        self.assertIn('YR_K8S_IMAGE_SDK_WHEEL_PATTERN: "openyuanrong_sdk*-${sdk_suffix}-*.whl"', pipeline)
        self.assertIn('SANDBOX_RUNTIME_IMAGE_STEPS: "${SANDBOX_RUNTIME_IMAGE_STEPS}"', pipeline)
        self.assertIn('BAZEL_OUTPUT_USER_ROOT="${output_root}"', sdk_build_script)
        self.assertIn('BAZEL_OUTPUT_BASE="${output_root}/output"', sdk_build_script)
        self.assertIn('bash "${ROOT_DIR}/build.sh" -p "${python_bin}" -v "${BUILD_VERSION}" -j "${SDK_BAZEL_JOBS}"', sdk_build_script)
        self.assertIn('cp -R "${ROOT_DIR}"/output/openyuanrong_sdk-*.whl "${OUTPUT_DIR}/"', sdk_build_script)
        self.assertIn("cp output/openyuanrong_sdk-*.whl artifacts/openyuanrong-sdk/", pipeline)
        self.assertNotIn("bazel \"${bazel_options[@]}\"", sdk_build_script)
        self.assertIn('SDK_BAZEL_JOBS="${SDK_BAZEL_JOBS:-8}"', sdk_build_script)
        self.assertIn('SDK_BAZEL_BUILD_ROOT="${SDK_BAZEL_BUILD_ROOT:-${ROOT_DIR}/build/sdk-${BUILDKITE_JOB_ID:-local}}"', sdk_build_script)
        self.assertIn('if [[ -z "${HOME:-}" ]]; then', sdk_build_script)
        self.assertIn('if [[ "$(uname)" == "Darwin" ]]; then', sdk_build_script)
        self.assertIn('dscl . -read "/Users/$(id -un)" NFSHomeDirectory', sdk_build_script)
        self.assertIn('getent passwd "$(id -u)"', sdk_build_script)
        self.assertIn('export HOME', sdk_build_script)
        self.assertIn('export BAZEL_REPOSITORY_CACHE=\\$\\$CACHE_BASE/bazel-repository-cache/arm64', pipeline)
        self.assertIn('--repository_cache=${BAZEL_REPOSITORY_CACHE}', (ROOT.parents[2] / "build.sh").read_text())
        self.assertIn('bash .buildkite/prepare_sdk_thirdparty_cache.sh "\\$\\$CACHE_BASE"', pipeline)
        self.assertIn("export SKIP_RUNTIME_DEPENDENCY_DOWNLOAD=1", pipeline)
        self.assertIn('SKIP_RUNTIME_DEPENDENCY_DOWNLOAD:-0', (ROOT.parents[2] / "build.sh").read_text())
        self.assertIn('THIRD_PARTY_CACHE_DIR="${CACHE_BASE}/thirdparty/sdk-${CACHE_ARCH}"', sdk_thirdparty_cache_script)
        self.assertIn('[ -d "${THIRD_PARTY_CACHE_DIR}/libboundscheck/include" ]', sdk_thirdparty_cache_script)
        self.assertIn('$1 == "boost" || $1 == "libboundscheck"', sdk_thirdparty_cache_script)
        self.assertIn('bash "${ROOT_DIR}/tools/download_opensource.sh"', sdk_thirdparty_cache_script)
        self.assertNotIn('bash "${ROOT_DIR}/tools/download_dependency.sh"', sdk_thirdparty_cache_script)
        self.assertIn('flock 9', sdk_thirdparty_cache_script)
        self.assertIn('ln -s "${THIRD_PARTY_CACHE_DIR}" "${ROOT_DIR}/thirdparty"', sdk_thirdparty_cache_script)
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
        self.assertIn("build-sdk-amd64-cp312", manifest_script)
        self.assertIn("build-sdk-arm64-cp312", manifest_script)
        self.assertIn("build-sdk-macos-arm64-cp312", manifest_script)
        self.assertNotIn('artifact download "artifacts/openyuanrong-sdk/*"', manifest_script)
        self.assertNotIn('artifact download "artifacts/release/*"', manifest_script)
        self.assertIn('buildkite-agent meta-data get "obs-urls.${step_key}"', manifest_script)
        self.assertIn("OBS credentials are required for manifest artifact upload.", manifest_script)
        self.assertIn('buildkite-agent artifact upload "${ARCHIVE_DIR}/index.html"', manifest_script)
        self.assertNotIn('buildkite-agent artifact upload "${SANDBOX_ARTIFACT_DIR}/**/*"', manifest_script)
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
        self.assertIn('cp314)', (ROOT / "build-images.sh").read_text())
        self.assertIn('cp314)', (ROOT.parent / "docker/build-images.sh").read_text())
        self.assertIn("verify_python314_sdk_wheel.sh", sdk_build_script)
        self.assertIn("verify_python314_runtime_image", package_script)
        self.assertIn("resolve_expected_sdk_version()", package_script)
        self.assertRegex(
            package_script,
            r"download_release_artifacts\s+resolve_expected_sdk_version\s+start_dockerd",
        )
        self.assertIn("build-python314-builder-amd64", pipeline)
        self.assertIn("build-python314-builder-arm64", pipeline)
        self.assertIn("publish-python314-builder-manifest", pipeline)
        self.assertNotIn("build-python314-rust-builder-amd64", pipeline)
        self.assertIn('local_images=(yr-runtime)', (ROOT / "push-images-swr.sh").read_text())
        self.assertIn('RUNTIME_IMAGE_STEPS="${SANDBOX_RUNTIME_IMAGE_STEPS:-}"', manifest_script)
        self.assertIn('DEFAULT_RUNTIME_SDK_SUFFIX="${YR_K8S_DEFAULT_RUNTIME_SDK_SUFFIX:-cp310}"', manifest_script)
        self.assertIn('RUNTIME_IMAGE_TAG="${YR_K8S_RUNTIME_IMAGE_TAG:-${IMAGE_TAG}-${DEFAULT_RUNTIME_SDK_SUFFIX}}"', manifest_script)
        self.assertIn('create_manifest "yr-runtime" "${IMAGE_TAG}-${sdk_suffix}" "-${sdk_suffix}"', manifest_script)
        self.assertIn("Runtime image tags", manifest_script)
        self.assertIn("https://api.buildkite.com/v2/packages/organizations/openyuanrong/registries/openyuanrong/packages", package_upload_script)
        self.assertIn('PACKAGE_UPLOAD_ENABLED="${BUILDKITE_PACKAGE_UPLOAD_ENABLED:-}"', package_upload_script)
        self.assertIn('if [ -n "${BUILDKITE_TAG:-}" ]; then', package_upload_script)
        self.assertIn('BUILDKITE_PACKAGE_UPLOAD_ENABLED is disabled; skipping Buildkite package upload.', package_upload_script)
        self.assertIn('PACKAGE_UPLOAD_TOKEN="${BUILDKITE_PACKAGE_UPLOAD_TOKEN:-${BUILDKITE_PACKAGES_TOKEN:-}}"', package_upload_script)
        self.assertIn('-F "file=@${file}"', package_upload_script)
        self.assertIn("bash .buildkite/upload_buildkite_packages.sh artifacts/release/*.whl", pipeline)
        self.assertIn('buildkite-agent meta-data set "obs-urls.${BUILDKITE_STEP_KEY}"', obs_upload_script)
        self.assertIn("tools/upload_build_artifact.py", obs_upload_script)
        self.assertIn('if ! "${OBS_PYTHON}" -c "from obs import ObsClient"', obs_upload_script)
        self.assertIn('-m venv "${OBS_VENV}"', obs_upload_script)
        self.assertIn("esdk-obs-python", obs_upload_script)
        self.assertIn("fnmatch.fnmatch", obs_download_script)
        self.assertIn('OBS_UPLOAD_CHANNEL="daily"', pipeline)
        self.assertIn('OBS_UPLOAD_CHANNEL="release"', pipeline)
        self.assertIn('OBS_UPLOAD_VERSION_ARGS="--version \\$\\$YR_BUILD_VERSION"', pipeline)
        self.assertIn('--channel "\\$\\$OBS_UPLOAD_CHANNEL"', pipeline)
        self.assertIn("bash .buildkite/upload_buildkite_packages.sh artifacts/openyuanrong-sdk/*.whl", pipeline)
        self.assertNotIn('artifact_paths:\n      - "artifacts/release/**/*"', pipeline)
        self.assertNotIn('artifact_paths:\n      - "artifacts/openyuanrong-sdk/**/*"', pipeline)
        self.assertNotIn('artifact_paths:\n      - "artifacts/sandbox/**/*"', pipeline)
        self.assertNotIn('artifact_paths:', pipeline)
        self.assertIn('local obs_channel="daily"', package_script)
        self.assertIn('obs_channel="release"', package_script)
        self.assertIn('version_args=(--version "${release_tag}")', package_script)
        self.assertIn('--channel "${obs_channel}"', package_script)
        self.assertIn('PUBLISH_TO_TEST_PYPI="${PUBLISH_TEST_PYPI:-}"', test_pypi_upload_script)
        self.assertIn('PUBLISH_TO_PYPI="${PUBLISH_PYPI:-}"', test_pypi_upload_script)
        self.assertIn('is_prerelease_version "${tag_version}"', test_pypi_upload_script)
        self.assertIn('PUBLISH_TO_PYPI=1', test_pypi_upload_script)
        self.assertIn('PYPI_API_TOKEN is required when PyPI publishing is enabled.', test_pypi_upload_script)
        self.assertIn('PyPI publishing is not enabled, skipping wheel upload.', test_pypi_upload_script)
        self.assertIn('PIP_BREAK_SYSTEM_PACKAGES=1 python3 -m pip "${pip_install_args[@]}"', test_pypi_upload_script)
        self.assertIn("--break-system-packages", test_pypi_upload_script)
        self.assertIn('python3 -m twine upload', test_pypi_upload_script)
        self.assertIn('--repository-url "${repository_url}"', test_pypi_upload_script)
        self.assertIn("buildkite-package-credentials", pipeline)
        self.assertIn("key: api-token", pipeline)
        self.assertIn('YR_K8S_SMOKE_SDK_WHEEL_PATTERN:-openyuanrong_sdk*-cp311-*.whl', smoke_script)
        self.assertIn('*-cp312-*) python_minor="3.12" ;;', smoke_script)
        self.assertIn('*-cp314-*) python_minor="3.14" ;;', smoke_script)
        self.assertIn("python@3.12", macos_tools)

    def test_test_pypi_publish_only_depends_on_emitted_sandbox_sdk_test(self):
        without_sandbox = emit_dynamic_pipeline(
            ENABLE_LINUX_ARM="false",
            ENABLE_MACOS_SDK="false",
            ENABLE_RUNTIME_X86="false",
            ENABLE_RUNTIME_ARM="false",
            ENABLE_SANDBOX_PACKAGE="false",
            ENABLE_TEST_PYPI_PUBLISH="true",
            SDK_PYTHON_VERSIONS="python3.11",
        )
        without_sandbox_steps = {
            step["key"]: step for step in flatten_pipeline_steps(without_sandbox)
        }
        self.assertNotIn("test-sandbox-sdk", without_sandbox_steps)
        self.assertEqual(
            without_sandbox_steps["publish-wheels-testpypi"]["env"][
                "SANDBOX_SANDBOX_SDK_STEPS"
            ],
            "",
        )
        self.assertNotIn(
            "test-sandbox-sdk",
            without_sandbox_steps["publish-wheels-testpypi"]["depends_on"],
        )
        publish_command = without_sandbox_steps["publish-wheels-testpypi"]["command"]
        self.assertIn('set -- --pattern \'openyuanrong_sdk*.whl\'', publish_command)
        self.assertIn(
            'if [ -n "$$SANDBOX_SANDBOX_SDK_STEPS" ]; then',
            publish_command,
        )
        self.assertIn(
            'set -- "$$@" --pattern \'openyuanrong_sandbox*.whl\'',
            publish_command,
        )
        self.assertIn('"$$@"', publish_command)

        with_sandbox = emit_dynamic_pipeline(
            ENABLE_LINUX_ARM="false",
            ENABLE_MACOS_SDK="false",
            ENABLE_RUNTIME_X86="false",
            ENABLE_RUNTIME_ARM="false",
            ENABLE_SANDBOX_PACKAGE="true",
            ENABLE_SANDBOX_MANIFEST="false",
            ENABLE_TEST_PYPI_PUBLISH="true",
            SDK_PYTHON_VERSIONS="python3.11",
        )
        with_sandbox_steps = {
            step["key"]: step for step in flatten_pipeline_steps(with_sandbox)
        }
        self.assertIn("test-sandbox-sdk", with_sandbox_steps)
        self.assertEqual(
            with_sandbox_steps["publish-wheels-testpypi"]["env"][
                "SANDBOX_SANDBOX_SDK_STEPS"
            ],
            "test-sandbox-sdk",
        )
        self.assertIn(
            "test-sandbox-sdk",
            with_sandbox_steps["publish-wheels-testpypi"]["depends_on"],
        )

    def test_python314_buildkite_execution_contract(self):
        packager = "registry.example.com/openyuanrong/sandbox-packager:test"
        bootstrap = emit_dynamic_pipeline(
            ENABLE_PYTHON314_BUILDER_BOOTSTRAP="true",
            SANDBOX_PACKAGER_IMAGE=packager,
        )
        product = emit_dynamic_pipeline(
            ENABLE_PYTHON314_BUILDER_BOOTSTRAP="false",
            SANDBOX_PACKAGER_IMAGE=packager,
            ENABLE_MACOS_SDK="true",
            ENABLE_LINUX_ARM="true",
            ENABLE_RUNTIME_X86="true",
            ENABLE_RUNTIME_ARM="true",
            ENABLE_SANDBOX_PACKAGE="true",
            ENABLE_SANDBOX_K8S_TEST="false",
            ENABLE_TEST_PYPI_PUBLISH="false",
            ENABLE_RUST_FUNCTIONSYSTEM_ST="false",
        )
        amd64_cp314_product = emit_dynamic_pipeline(
            ENABLE_PYTHON314_BUILDER_BOOTSTRAP="false",
            ENABLE_MACOS_SDK="true",
            ENABLE_LINUX_ARM="false",
            ENABLE_RUNTIME_X86="true",
            ENABLE_RUNTIME_ARM="false",
            ENABLE_SANDBOX_PACKAGE="true",
            ENABLE_SANDBOX_MANIFEST="false",
            ENABLE_SANDBOX_K8S_TEST="false",
            ENABLE_TEST_PYPI_PUBLISH="false",
            ENABLE_RUST_FUNCTIONSYSTEM_ST="false",
            SDK_PYTHON_VERSIONS="python3.14",
            SANDBOX_RUNTIME_IMAGE_PYTHON_VERSIONS="python3.14",
        )
        bootstrap_steps = {step["key"]: step for step in flatten_pipeline_steps(bootstrap)}
        product_steps = {step["key"]: step for step in flatten_pipeline_steps(product)}
        amd64_cp314_steps = {
            step["key"]: step for step in flatten_pipeline_steps(amd64_cp314_product)
        }
        bootstrap_keys = {
            "build-python314-builder-amd64",
            "build-python314-builder-arm64",
            "publish-python314-builder-manifest",
        }
        self.assertEqual(set(bootstrap_steps), bootstrap_keys)
        self.assertTrue(bootstrap_keys.isdisjoint(product_steps))
        self.assertIn(
            "build-sdk-amd64-cp314",
            amd64_cp314_steps["publish-sandbox-release-amd64"]["depends_on"],
        )
        self.assertNotIn(
            "build-sdk-amd64-cp311",
            amd64_cp314_steps["publish-sandbox-release-amd64"]["depends_on"],
        )
        self.assertIn("build-sdk-macos-arm64-cp314", amd64_cp314_steps)
        self.assertFalse(any("arm64" in key and "macos" not in key for key in amd64_cp314_steps))
        self.assertNotIn("publish-sandbox-manifest", amd64_cp314_steps)
        self.assertEqual(
            set(bootstrap_steps["publish-python314-builder-manifest"]["depends_on"]),
            bootstrap_keys - {"publish-python314-builder-manifest"},
        )
        for key in {
            "build-python314-builder-amd64",
            "publish-python314-builder-manifest",
        }:
            with self.subTest(bootstrap_executor=key):
                step = bootstrap_steps[key]
                self.assertEqual(pipeline_step_container(step)["image"], packager)

        standard_base = (
            "swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev/"
            "compile-ubuntu2004:v20260428_cmake33110"
        )
        existing_rust_builder = (
            "swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev/"
            "compile-ubuntu2004-rust:v20260507_x86_64"
        )
        self.assertEqual(
            bootstrap_steps["build-python314-builder-amd64"]["env"]["PYTHON314_BUILDER_BASE_IMAGE"],
            standard_base,
        )
        self.assertEqual(
            bootstrap_steps["build-python314-builder-arm64"]["env"]["PYTHON314_BUILDER_BASE_IMAGE"],
            standard_base,
        )
        self.assertEqual(
            pipeline_step_container(bootstrap_steps["build-python314-builder-arm64"])["image"],
            standard_base,
        )
        python314_builder = standard_base.replace(":v20260428_cmake33110", ":v20260714_py3146")
        self.assertEqual(
            pipeline_step_container(product_steps["build-all-amd64"])["image"],
            python314_builder,
        )
        self.assertEqual(
            pipeline_step_container(product_steps["build-sdk-amd64-cp314"])["image"],
            python314_builder,
        )
        self.assertEqual(
            pipeline_step_container(product_steps["build-rrt-amd64"])["image"],
            existing_rust_builder,
        )

        amd64_docker_step_keys = {
            "publish-sandbox-release-amd64",
            "publish-sandbox-manifest",
            *{
                f"publish-runtime-amd64-{suffix}"
                for suffix in ("cp39", "cp310", "cp311", "cp312", "cp313", "cp314")
            },
        }
        for key in amd64_docker_step_keys:
            with self.subTest(product_executor=key):
                step = product_steps[key]
                container = pipeline_step_container(step)
                self.assertEqual(container["image"], packager)
                secret_names = {entry["name"] for entry in container["env"]}
                self.assertTrue(
                    {"SWR_USERNAME", "SWR_PASSWORD", "SWR_DOCKER_CONFIG_JSON"}.issubset(secret_names)
                )

        for key in {
            "publish-sandbox-release-arm64",
            *{f"publish-runtime-arm64-{suffix}" for suffix in ("cp39", "cp310", "cp311", "cp312", "cp313", "cp314")},
        }:
            with self.subTest(arm64_product_step=key):
                step = product_steps[key]
                self.assertEqual(pipeline_step_container(step)["image"], python314_builder)
                self.assertEqual(step["agents"]["linux_arch"], "arm64")
                self.assertEqual(
                    step["plugins"][0]["kubernetes"]["podSpec"]["nodeSelector"]["kubernetes.io/arch"],
                    "arm64",
                )
        bootstrap_arm = bootstrap_steps["build-python314-builder-arm64"]
        self.assertEqual(bootstrap_arm["agents"]["linux_arch"], "arm64")
        self.assertEqual(
            bootstrap_arm["plugins"][0]["kubernetes"]["podSpec"]["nodeSelector"]["kubernetes.io/arch"],
            "arm64",
        )

        cp314_sdk_keys = {
            "build-sdk-amd64-cp314",
            "build-sdk-arm64-cp314",
            "build-sdk-macos-arm64-cp314",
        }
        self.assertTrue(cp314_sdk_keys.issubset(product_steps))
        self.assertIn(
            "build-sdk-amd64-cp314",
            product_steps["publish-runtime-amd64-cp314"]["depends_on"],
        )
        self.assertIn(
            "build-sdk-arm64-cp314",
            product_steps["publish-runtime-arm64-cp314"]["depends_on"],
        )
        manifest_dependencies = set(product_steps["publish-sandbox-manifest"]["depends_on"])
        self.assertTrue(cp314_sdk_keys.issubset(manifest_dependencies))
        self.assertTrue(
            {"publish-runtime-amd64-cp314", "publish-runtime-arm64-cp314"}.issubset(
                manifest_dependencies
            )
        )

        repo = ROOT.parents[2]
        packager_dockerfile = (repo / "ci/sandbox-packager/Dockerfile").read_text()
        helper = repo / ".buildkite/docker_job_helpers.sh"
        manifest_script = (repo / ".buildkite/package_sandbox_manifest.sh").read_text()
        release_script = (repo / ".buildkite/package_sandbox_release.sh").read_text()
        sdk_verifier = (repo / ".buildkite/verify_python314_sdk_wheel.sh").read_text()
        builder_script = (repo / ".buildkite/build_python314_builder_image.sh").read_text()
        self.assertIn("ARG TARGETARCH", packager_dockerfile)
        self.assertIn('arm64) HELM_ARCH="arm64"; KUBECTL_ARCH="arm64"', packager_dockerfile)
        self.assertTrue(helper.is_file())
        helper_text = helper.read_text()
        self.assertIn("overlay2", helper_text)
        self.assertIn("vfs", helper_text)
        self.assertIn("Docker daemon failed", helper_text)
        self.assertIn("verify_image_manifest.py", manifest_script)
        self.assertIn("require_cp314_sdk_records", manifest_script)
        self.assertIn("image-manifest-evidence.tsv", manifest_script)
        self.assertIn("EXPECTED_SDK_VERSION", release_script)
        self.assertIn('installed_version == expected_version', release_script)
        self.assertIn('wheel_listing="$(unzip -l "${wheel}")"', sdk_verifier)
        self.assertNotIn('unzip -l "${wheel}" |', sdk_verifier)
        self.assertIn('if [ "${VARIANT}" = compile ]; then', builder_script)

    def test_image_manifest_validator_rejects_wrong_platform_and_duplicates(self):
        verifier = ROOT.parents[2] / ".buildkite/verify_image_manifest.py"
        self.assertTrue(verifier.is_file())
        digest_amd64 = "sha256:" + "a" * 64
        digest_arm64 = "sha256:" + "b" * 64
        final_digest = "sha256:" + "c" * 64
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = pathlib.Path(tmpdir)
            source = tmp / "source.json"
            source.write_text(
                json.dumps(
                    {
                        "Descriptor": {
                            "digest": digest_amd64,
                            "platform": {"os": "linux", "architecture": "amd64"},
                        }
                    }
                )
            )
            evidence = tmp / "evidence.tsv"
            source_args = [
                str(PYTHON_BIN),
                str(verifier),
                "source",
                "--input",
                str(source),
                "--image",
                "registry.example.com/yr-runtime:test-amd64",
                "--evidence",
                str(evidence),
            ]
            subprocess.run(
                [*source_args, "--expected-platform", "linux/amd64"],
                check=True,
                capture_output=True,
                text=True,
            )
            wrong_source = subprocess.run(
                [*source_args, "--expected-platform", "linux/arm64"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(wrong_source.returncode, 0)

            final = tmp / "final.json"
            final.write_text(
                json.dumps(
                    {
                        "manifests": [
                            {
                                "digest": digest_amd64,
                                "platform": {"os": "linux", "architecture": "amd64"},
                            },
                            {
                                "digest": digest_arm64,
                                "platform": {"os": "linux", "architecture": "arm64"},
                            },
                        ]
                    }
                )
            )
            final_args = [
                str(PYTHON_BIN),
                str(verifier),
                "final",
                "--input",
                str(final),
                "--image",
                "registry.example.com/yr-runtime:test",
                "--digest",
                final_digest,
                "--expected-platform",
                "linux/amd64",
                "--expected-platform",
                "linux/arm64",
                "--evidence",
                str(evidence),
            ]
            subprocess.run(final_args, check=True, capture_output=True, text=True)
            duplicate = json.loads(final.read_text())
            duplicate["manifests"][1]["platform"]["architecture"] = "amd64"
            final.write_text(json.dumps(duplicate))
            wrong_final = subprocess.run(final_args, check=False, capture_output=True, text=True)
            self.assertNotEqual(wrong_final.returncode, 0)
            evidence_text = evidence.read_text()
            self.assertIn(digest_amd64, evidence_text)
            self.assertIn(final_digest, evidence_text)
            self.assertIn("linux/amd64,linux/arm64", evidence_text)

    def test_manifest_publish_requires_cp314_metadata_before_registry_mutation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = pathlib.Path(tmpdir)
            docker_log = tmp / "docker.log"
            fake_docker = tmp / "docker"
            fake_docker.write_text(
                "#!/usr/bin/env bash\n"
                'printf "%s\\n" "$*" >>"${DOCKER_LOG}"\n'
                "exit 0\n"
            )
            fake_docker.chmod(0o755)
            fake_agent = tmp / "buildkite-agent"
            fake_agent.write_text("#!/usr/bin/env bash\nexit 0\n")
            fake_agent.chmod(0o755)
            env = dict(os.environ)
            env.update(
                {
                    "PATH": f"{tmp}:{env['PATH']}",
                    "DOCKER_BIN": str(fake_docker),
                    "DOCKER_LOG": str(docker_log),
                    "SANDBOX_ARTIFACT_DIR": str(tmp / "artifacts"),
                    "BUILDKITE_STEP_KEY": "publish-sandbox-manifest",
                }
            )
            result = subprocess.run(
                [str(BASH_BIN), ".buildkite/package_sandbox_manifest.sh"],
                cwd=ROOT.parents[2],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Required Python 3.14 SDK metadata is missing or empty", result.stderr)
            self.assertFalse(docker_log.exists(), "registry mutation must not begin without cp314 records")

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
