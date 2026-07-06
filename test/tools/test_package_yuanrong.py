#!/usr/bin/env python3
# coding=UTF-8

"""Regression tests for package_yuanrong.sh layout contracts."""

import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PACKAGE_SCRIPT = REPO_ROOT / "scripts" / "package_yuanrong.sh"
PREPARE_ST_SCRIPT = REPO_ROOT / "test" / "st" / "prepare_and_start_yr.sh"
ST_TEST_SCRIPT = REPO_ROOT / "test" / "st" / "test.sh"
PYTHON_SETUP = REPO_ROOT / "api" / "python" / "setup.py"


class PackageYuanrongLayoutTest(unittest.TestCase):
    def test_dashboard_package_layout_matches_split_wheel_source(self):
        """Dashboard package assembly must populate the directory used by its split wheel."""
        package_script = PACKAGE_SCRIPT.read_text(encoding="utf-8")
        python_setup = PYTHON_SETUP.read_text(encoding="utf-8")

        self.assertIn('dashboard_dir = os.path.join(root_dir, "dashboard")', python_setup)
        self.assertIn('"${OUTPUT_DIR}/openyuanrong/dashboard/"', package_script)
        self.assertNotIn(
            'copy_dashboard_stage_or_extract_tar "${DASHBOARD_STAGE_DIR}" '
            '"${dashboard_filename}" "${OUTPUT_DIR}/openyuanrong/functionsystem/"',
            package_script,
        )

    def test_st_failure_dumps_deploy_diagnostics(self):
        """ST failures should include component logs, not only driver output."""
        test_script = ST_TEST_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("dump_st_failure_diagnostics", test_script)
        self.assertIn("dump_failed_runtime_logs", test_script)
        self.assertIn("grep -hoE 'runtime-[[:alnum:]_.:-]+'", test_script)
        self.assertIn("[gate-st] tail failed runtime", test_script)
        self.assertIn("[gate-st] ST failed, dump deploy diagnostics", test_script)
        self.assertIn("function_master|function_proxy|function_agent", test_script)

        failure_msg = 'echo "----------------------Failed to run ${language} st----------------------"'
        first_failure = test_script.index(failure_msg)
        first_dump = test_script.index("dump_st_failure_diagnostics", first_failure)
        self.assertLess(first_failure, first_dump)

    def test_process_st_installs_runtime_python_requirements_before_deploy(self):
        """Process-mode runtime services must see Python requirements such as protobuf."""
        test_script = ST_TEST_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("install_python_runtime_service_deps", test_script)
        self.assertIn('${YUANRONG_DIR}/runtime/service/python/requirements.txt', test_script)
        self.assertIn('${BASE_DIR}/../../api/python/requirements.txt', test_script)
        self.assertIn('${DEPLOY_PATH}/python_runtime_deps', test_script)
        self.assertIn('python3.9 -m pip install numpy -t "${runtime_deps_dir}"', test_script)
        self.assertIn('export PYTHONPATH="${runtime_deps_dir}', test_script)

        install_call = "\n        install_python_runtime_service_deps\n"
        deploy_call = "\n        bash prepare_and_start_yr.sh"
        install_pos = test_script.index(install_call)
        deploy_pos = test_script.index(deploy_call, install_pos)
        self.assertLess(install_pos, deploy_pos)

    def test_process_st_installs_driver_sdk_before_runtime_python_deps(self):
        """Driver SDK install must not remove the runtime dependency target dir."""
        test_script = ST_TEST_SCRIPT.read_text(encoding="utf-8")

        process_branch = test_script.index('if [[ "$DEPLOY_MODE" == "process" ]]')
        driver_install_pos = test_script.index("\n            install_python_pkg\n", process_branch)
        runtime_install_pos = test_script.index("\n        install_python_runtime_service_deps\n", process_branch)
        deploy_pos = test_script.index("\n        bash prepare_and_start_yr.sh", runtime_install_pos)

        self.assertLess(driver_install_pos, runtime_install_pos)
        self.assertLess(runtime_install_pos, deploy_pos)

    def test_runtime_wheel_keeps_python_metrics_exporters(self):
        """Runtime split wheel must include Python runtime metrics exporter plugins."""
        python_setup = PYTHON_SETUP.read_text(encoding="utf-8")

        self.assertIn("PYTHON_RUNTIME_METRICS_EXPORTERS", python_setup)
        self.assertIn('"libobservability-metrics-file-exporter.so"', python_setup)
        self.assertIn('"libobservability-prometheus-push-exporter.so"', python_setup)
        self.assertIn('"libobservability-prometheus-pull-exporter.so"', python_setup)
        self.assertNotIn('"libobservability-aom-alarm-exporter.so"', python_setup)
        self.assertIn("copy_python_runtime_metrics_exporters(build_lib, runtime_dir)", python_setup)
        self.assertIn(
            'os.path.join(build_lib, "yr/runtime/service/python/yr")',
            python_setup,
        )


if __name__ == "__main__":
    unittest.main()
