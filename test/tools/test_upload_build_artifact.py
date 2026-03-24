import importlib.util
import pathlib
import unittest


SCRIPT_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "upload_build_artifact.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("upload_build_artifact", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BuildObjectPathTests(unittest.TestCase):
    def test_daily_build_path_includes_timestamp_platform_arch(self):
        module = load_module()

        path = module.build_object_path(
            kind="build",
            channel="daily",
            file_path="/tmp/pkg.whl",
            platform="linux",
            arch="x86_64",
            timestamp="20260324153000",
        )

        self.assertEqual(path, "daily/20260324153000/linux/x86_64/pkg.whl")

    def test_release_build_path_includes_version_platform_arch(self):
        module = load_module()

        path = module.build_object_path(
            kind="build",
            channel="release",
            file_path="/tmp/pkg.whl",
            platform="linux",
            arch="aarch64",
            version="1.2.3",
        )

        self.assertEqual(path, "release/1.2.3/linux/aarch64/pkg.whl")

    def test_thirdparty_path_uses_explicit_target_only(self):
        module = load_module()

        path = module.build_object_path(
            kind="thirdparty",
            file_path="/tmp/boost.tar.zst",
            target="boost/prebuilt/linux-x86_64",
        )

        self.assertEqual(
            path, "thirdparty/boost/prebuilt/linux-x86_64/boost.tar.zst"
        )

    def test_thirdparty_path_can_be_derived_from_source_url(self):
        module = load_module()

        source_url = (
            "https://github.com/open-telemetry/opentelemetry-cpp/"
            "archive/refs/tags/v1.13.0.tar.gz"
        )

        path = module.build_object_path(
            kind="thirdparty",
            file_path=None,
            source_url=source_url,
        )

        self.assertEqual(
            path,
            "thirdparty/github.com/open-telemetry/opentelemetry-cpp/v1.13.0.tar.gz",
        )


class ThirdpartyUrlResolutionTests(unittest.TestCase):
    def test_default_target_is_derived_from_upstream_url(self):
        module = load_module()

        source_url = (
            "https://github.com/open-telemetry/opentelemetry-cpp/"
            "archive/refs/tags/v1.13.0.tar.gz"
        )

        target = module.derive_thirdparty_target(source_url)

        self.assertEqual(target, "github.com/open-telemetry/opentelemetry-cpp")

    def test_filename_is_derived_from_source_url(self):
        module = load_module()

        filename = module.derive_filename(
            source_url="https://example.com/pkg/cache/boost-1.0.0.tar.zst"
        )

        self.assertEqual(filename, "boost-1.0.0.tar.zst")

    def test_github_archive_url_is_rewritten_to_codeload(self):
        module = load_module()

        url = (
            "https://github.com/open-telemetry/opentelemetry-cpp/"
            "archive/refs/tags/v1.13.0.tar.gz"
        )

        rewritten = module.normalize_source_url(url)

        self.assertEqual(
            rewritten,
            "https://codeload.github.com/open-telemetry/opentelemetry-cpp/tar.gz/refs/tags/v1.13.0",
        )


class ArgumentValidationTests(unittest.TestCase):
    def test_release_requires_version(self):
        module = load_module()

        with self.assertRaisesRegex(ValueError, "--version is required"):
            module.validate_args(
                kind="build",
                channel="release",
                version=None,
                target=None,
                file_path="/tmp/pkg.whl",
                source_url=None,
            )

    def test_thirdparty_requires_target_or_source_url(self):
        module = load_module()

        with self.assertRaisesRegex(ValueError, "--target or --source-url is required"):
            module.validate_args(
                kind="thirdparty",
                channel=None,
                version=None,
                target=None,
                file_path=None,
                source_url=None,
            )

    def test_thirdparty_rejects_build_channel(self):
        module = load_module()

        with self.assertRaisesRegex(ValueError, "does not support --channel"):
            module.validate_args(
                kind="thirdparty",
                channel="daily",
                version=None,
                target="boost/src",
                file_path="/tmp/boost.tar.zst",
                source_url=None,
            )

    def test_thirdparty_accepts_source_url_without_target(self):
        module = load_module()

        module.validate_args(
            kind="thirdparty",
            channel=None,
            version=None,
            target=None,
            file_path=None,
            source_url="https://github.com/open-telemetry/opentelemetry-cpp/archive/refs/tags/v1.13.0.tar.gz",
        )


if __name__ == "__main__":
    unittest.main()
