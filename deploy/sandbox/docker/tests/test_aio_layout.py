import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[2]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def python_builder_section(text: str) -> str:
    return (ROOT.parent / "images" / "Dockerfile.base").read_text()


class AioLayoutTests(unittest.TestCase):
    def test_runtime_image_is_split_out(self):
        runtime_dockerfile = ROOT / "Dockerfile.runtime"
        self.assertTrue(runtime_dockerfile.exists(), "Dockerfile.runtime should exist")
        runtime_text = runtime_dockerfile.read_text()
        base_text = python_builder_section(runtime_text)
        self.assertIn("ARG BASE_IMAGE=yr-base", runtime_text)
        self.assertIn("FROM ${BASE_IMAGE}", runtime_text)
        self.assertIn("openyuanrong_sdk", runtime_text)
        self.assertIn("ca-certificates", base_text)
        self.assertIn("python3-pip", base_text)
        self.assertIn("uv==0.11.11", base_text)
        self.assertIn("mirrors.huaweicloud.com/repository/pypi/simple", base_text)
        self.assertIn('uv python install "${PYTHON_VERSION}"', base_text)
        self.assertIn("COPY openyuanrong_sdk*.whl", runtime_text)
        self.assertIn('ln -sf "${python_bin_dir}/yrcli" /usr/local/bin/yrcli', runtime_text)
        self.assertNotIn("COPY pkg/", runtime_text)
        self.assertNotIn("openyuanrong-", runtime_text)
        self.assertNotIn("runtime-launcher", runtime_text)
        self.assertNotIn(" AS python-builder", runtime_text)
        self.assertNotIn(" AS python-builder", base_text)
        self.assertNotIn("build-essential", base_text)
        self.assertNotIn("Python-${PYTHON_VERSION}", base_text)

    def test_runtime_image_includes_libcurl(self):
        base_text = (ROOT.parent / "images" / "Dockerfile.base").read_text()
        self.assertIn("libcurl4", base_text)

    def test_main_image_is_split_out(self):
        main_dockerfile = ROOT / "Dockerfile.aio-yr"
        self.assertTrue(main_dockerfile.exists(), "Dockerfile.aio-yr should exist")
        main_text = main_dockerfile.read_text()
        self.assertIn("ARG CONTROLPLANE_IMAGE=yr-controlplane", main_text)
        self.assertIn("FROM ${CONTROLPLANE_IMAGE}", main_text)
        self.assertIn("dockerd", main_text)
        self.assertIn("ca-certificates", python_builder_section(main_text))
        self.assertNotIn("COPY openyuanrong_sdk*.whl", main_text)
        self.assertNotIn("COPY openyuanrong-*.whl", main_text)
        self.assertIn("COPY runtime-launcher /openyuanrong/runtime-launcher", main_text)
        self.assertIn("COPY --from=deploy services.yaml", main_text)
        self.assertNotIn("COPY pkg/", main_text)
        self.assertNotIn("openclaw", main_text)
        self.assertNotIn("claude-code", main_text)
        self.assertNotIn(" AS python-builder", main_text)

    def test_services_use_runtime_image(self):
        services_text = read_text("services.yaml")
        self.assertIn('imageurl: "aio-yr-runtime:latest"', services_text)

    def test_traefik_routes_http_to_frontend(self):
        dynamic_text = read_text("traefik/dynamic.yml")
        traefik_text = read_text("traefik/traefik.yml")
        self.assertIn("web:", traefik_text)
        self.assertIn('__AIO_NODE_IP__:32379', traefik_text)
        self.assertIn("frontend-root", dynamic_text)
        self.assertIn('url: "http://__AIO_NODE_IP__:8889"', dynamic_text)
        self.assertNotIn("redirect-to-https", dynamic_text)
        self.assertNotIn("tls:", dynamic_text)

    def test_supervisord_entrypoint_starts_dockerd_before_supervisord(self):
        entrypoint_text = read_text("supervisord-entrypoint.sh")
        self.assertIn('AIO_NODE_IP="$(hostname -i | awk \'{print $1}\')"', entrypoint_text)
        self.assertIn("dockerd --host", entrypoint_text)
        self.assertIn("docker info", entrypoint_text)
        self.assertIn("docker load", entrypoint_text)
        self.assertIn('sed -i "s/__AIO_NODE_IP__/${AIO_NODE_IP}/g" /openyuanrong/traefik/dynamic.yml /openyuanrong/traefik/traefik.yml', entrypoint_text)
        self.assertIn("exec /usr/bin/supervisord", entrypoint_text)

    def test_supervisord_runs_yuanrong_in_blocking_mode(self):
        supervisord_text = read_text("supervisord.conf")
        self.assertIn("[program:yuanrong-master]", supervisord_text)
        self.assertIn("command=/usr/local/bin/start-yuanrong.sh", supervisord_text)
        self.assertIn("[program:seed-traefik-etcd]", supervisord_text)
        self.assertIn("command=/usr/local/bin/seed-traefik-etcd.sh", supervisord_text)
        self.assertIn("autorestart=true", supervisord_text)

    def test_start_yuanrong_script_uses_container_ip(self):
        script_text = read_text("start-yuanrong.sh")
        self.assertIn('AIO_NODE_IP="$(hostname -i | awk \'{print $1}\')"', script_text)
        self.assertIn("--block true", script_text)
        self.assertIn("--enable_traefik_registry true", script_text)
        self.assertIn("--traefik_http_entrypoint web", script_text)
        self.assertIn('-a "${AIO_NODE_IP}"', script_text)
        self.assertNotIn("-a 127.0.0.1", script_text)

    def test_seed_traefik_script_initializes_root_key(self):
        script_text = read_text("seed-traefik-etcd.sh")
        self.assertIn('ETCD_ENDPOINT="${AIO_NODE_IP}:32379"', script_text)
        self.assertIn('put traefik/_keepalive 1', script_text)

    def test_supervisord_entrypoint_retries_vfs_when_dockerd_exits_early(self):
        entrypoint_lines = read_text("supervisord-entrypoint.sh").splitlines()
        kill_check_index = next(
            i for i, line in enumerate(entrypoint_lines) if "if ! kill -0" in line
        )
        retry_index = next(
            i for i, line in enumerate(entrypoint_lines) if "retrying with vfs" in line
        )

        intervening = entrypoint_lines[kill_check_index:retry_index]
        self.assertNotIn("        exit 1", intervening)
        self.assertIn("        break", intervening)

    def test_dockerd_entrypoint_falls_back_to_vfs(self):
        dockerd_text = read_text("dockerd-entrypoint.sh")
        self.assertIn("overlay2", dockerd_text)
        self.assertIn("vfs", dockerd_text)
        self.assertIn("start_dockerd", dockerd_text)

    def test_readme_uses_privileged_dind_instructions(self):
        readme_text = read_text("README.md")
        self.assertIn("--privileged", readme_text)
        self.assertNotIn("/var/run/docker.sock", readme_text)
        self.assertIn("Dockerfile.aio-yr", readme_text)
        self.assertIn("Dockerfile.runtime", readme_text)
        self.assertIn("build-images.sh", readme_text)

    def test_build_script_uses_output_as_docker_context(self):
        script_text = read_text("build-images.sh")
        self.assertIn('"${OUTPUT_DIR}"', script_text)
        self.assertIn('--build-context deploy="${SCRIPT_DIR}"', script_text)
        self.assertIn("yr-base", script_text)
        self.assertIn("yr-runtime", script_text)
        self.assertIn("yr-controlplane", script_text)
        self.assertNotIn('"${REPO_ROOT}"', script_text)
        self.assertNotIn("/pkg/", script_text)

    def test_run_script_builds_and_starts_aio(self):
        script_path = ROOT / "run.sh"
        self.assertTrue(script_path.exists(), "run.sh should exist")
        script_text = script_path.read_text()
        self.assertNotIn("make all", script_text)
        self.assertNotIn("make image", script_text)
        self.assertIn("docker compose", script_text)
        self.assertIn("docker-compose.yml", script_text)
        self.assertNotIn("docker run", script_text)
        self.assertIn('AIO_CONTAINER_NAME:-aio-yr', script_text)

    def test_aio_compose_matches_runtime_requirements(self):
        compose_path = ROOT / "docker-compose.yml"
        self.assertTrue(compose_path.exists(), "docker-compose.yml should exist")
        compose_text = compose_path.read_text()
        self.assertIn("container_name: ${AIO_CONTAINER_NAME:-aio-yr}", compose_text)
        self.assertIn("image: ${AIO_IMAGE_NAME:-aio-yr:latest}", compose_text)
        self.assertIn('published: "${AIO_PORT:-38888}"', compose_text)
        self.assertIn("target: 8888", compose_text)
        self.assertIn("privileged: true", compose_text)
        self.assertIn("cgroup: host", compose_text)
    def test_host_sdk_script_uses_frontend_address_with_in_cluster_false(self):
        script_path = ROOT / "create-sandbox-host.sh"
        self.assertTrue(script_path.exists(), "create-sandbox-host.sh should exist")
        script_text = script_path.read_text()
        self.assertIn('server_address = os.environ["YR_HOST_SERVER_ADDRESS"]', script_text)
        self.assertIn("cfg.in_cluster = False", script_text)
        self.assertIn('YR_HOST_SERVER_ADDRESS:-127.0.0.1:38888', script_text)
        self.assertIn("openyuanrong_sdk-0.7.0.dev0-cp39-cp39-manylinux_2_34_x86_64.whl", script_text)

    def test_port_forward_verification_script_uses_detached_sandbox(self):
        script_path = ROOT / "verify-port-forward-host.sh"
        self.assertTrue(script_path.exists(), "verify-port-forward-host.sh should exist")
        script_text = script_path.read_text()
        self.assertIn('opt.custom_extensions["lifecycle"] = "detached"', script_text)
        self.assertIn("opt.port_forwardings = [PortForwarding(port=port)]", script_text)
        self.assertIn('["curl", "-sk", "-o", "-", "-w", "\\nHTTP_STATUS:%{http_code}\\n", url]', script_text)
        self.assertIn('yr.kill_instance(instance_id)', script_text)

    def test_webterminal_uses_direct_sandbox_create_flow(self):
        webterm_text = (
            REPO_ROOT / "frontend/pkg/frontend/webui/webterm.go"
        ).read_text()
        self.assertIn("extractSandboxCreateInstanceId", webterm_text)
        self.assertIn("fetch('%s/api/sandbox/create'", webterm_text)
        self.assertIn("parseTenantFromJWT(token) || tenant", webterm_text)

    def test_runtime_launcher_proto_keeps_ports_field_in_sync(self):
        launcher_proto = (
            REPO_ROOT / "functionsystem/runtime-launcher/api/proto/runtime/v1/runtime_launcher.proto"
        ).read_text()
        interface_proto = (
            REPO_ROOT / "functionsystem/proto/posix/runtime_launcher_interface.proto"
        ).read_text()
        self.assertIn("repeated string ports = 11;", launcher_proto)
        self.assertIn("repeated string ports = 11;", interface_proto)
        self.assertIn("string trace_id = 10;", launcher_proto)
        self.assertIn("string trace_id = 10;", interface_proto)


if __name__ == "__main__":
    unittest.main()
