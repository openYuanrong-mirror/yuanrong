workspace(name = "yuanrong_multi_language_runtime")

load("//bazel:hazel_workspace.bzl", "hw_rules")

hw_rules()

# Note: rules_foreign_cc and rules_go are not needed for macOS C++/Python builds
# They require network downloads which may fail without proxy
# load("@rules_foreign_cc//foreign_cc:repositories.bzl", "rules_foreign_cc_dependencies")
# rules_foreign_cc_dependencies()

# load("@io_bazel_rules_go//go:deps.bzl", "go_register_toolchains", "go_rules_dependencies")
# go_rules_dependencies()
# go_register_toolchains(version = "1.24.1")

load("@bazel_gazelle//:deps.bzl", "gazelle_dependencies")

gazelle_dependencies()

load("@rules_python//python:repositories.bzl", "python_register_toolchains")
python_register_toolchains(
    name = "python3_9",
    ignore_root_user_error = True,
    python_version = "3.9.15",
    register_toolchains = False,
    register_coverage_tool = True,
)

load("@python3_9//:defs.bzl", python39 = "interpreter")
load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")
load("@bazel_tools//tools/build_defs/repo:git.bzl", "git_repository")
load("@bazel_tools//tools/build_defs/repo:git.bzl", "new_git_repository")
load("@bazel_tools//tools/build_defs/repo:utils.bzl", "maybe")
load("//bazel:host_platform_repo.bzl", "host_platform_repo")
load("//bazel:platform_local_repository.bzl", "platform_local_repository")

host_platform_repo(name = "host_platform")

http_archive(
    name = "rules_jvm_external",
    sha256 = "b17d7388feb9bfa7f2fa09031b32707df529f26c91ab9e5d909eb1676badd9a6",
    strip_prefix = "rules_jvm_external-4.5",
    url = "https://github.com/bazel-contrib/rules_jvm_external/archive/refs/tags/4.5.zip",
)

load("@rules_jvm_external//:defs.bzl", "maven_install")

maven_install(
    artifacts = [
        "com.google.code.gson:gson:2.11.0",
        "org.apache.commons:commons-lang3:3.18.0",
        "org.apache.maven.plugins:maven-assembly-plugin:3.4.2",
        "org.apache.maven.plugins:maven-compiler-plugin:3.10.1",
        "commons-io:commons-io:2.16.1",
        "org.json:json:20230227",
        "org.msgpack:jackson-dataformat-msgpack:0.9.3",
        "org.msgpack:msgpack-core:0.9.3",
        "com.fasterxml.jackson.core:jackson-core:2.18.2",
        "com.fasterxml.jackson.core:jackson-databind:2.18.2",
        "org.apache.logging.log4j:log4j-slf4j-impl:2.23.1",
        "org.apache.logging.log4j:log4j-api:2.23.1",
        "org.apache.logging.log4j:log4j-core:2.23.1",
        "org.slf4j:slf4j-api:1.7.36",
        "org.powermock:powermock-module-junit4:2.0.4",
        "org.powermock:powermock-api-mockito2:2.0.4",
        "junit:junit:4.11",
        "org.jacoco:org.jacoco.agent:0.8.8",
        "org.projectlombok:lombok:1.18.36",
        "org.ow2.asm:asm:9.7",
    ],
    repositories = [
        "https://mirrors.huaweicloud.com/repository/maven/",
    ],
)

http_archive(
    name = "spdlog",
    build_file = "@//bazel:spdlog.bzl",
    sha256 = "6174bf8885287422a6c6a0312eb8a30e8d22bcfcee7c48a6d02d1835d7769232",
    strip_prefix = "spdlog-1.12.0",
    urls = ["https://github.com/gabime/spdlog/archive/refs/tags/v1.12.0.zip"],
    patches = [
         "@//patch:spdlog-change-namespace-and-library-name-with-yr.patch",
    ]
)

http_archive(
    name = "nlohmann_json",
    build_file = "@//bazel:nlohmann_json.bzl",
    sha256 = "04022b05d806eb5ff73023c280b68697d12b93e1b7267a0b22a1a39ec7578069",
    strip_prefix = "json-3.11.3",
    urls = ["https://github.com/nlohmann/json/archive/v3.11.3.zip"],
)

http_archive(
    name = "gtest",
    sha256 = "ffa17fbc5953900994e2deec164bb8949879ea09b411e07f215bfbb1f87f4632",
    strip_prefix = "googletest-1.13.0",
    urls = ["https://github.com/google/googletest/archive/refs/tags/v1.13.0.zip"],
)

http_archive(
    name = "remote_coverage_tools",
    sha256 = "7006375f6756819b7013ca875eab70a541cf7d89142d9c511ed78ea4fefa38af",
    urls = [
        "https://mirror.bazel.build/bazel_coverage_output_generator/releases/coverage_output_generator-v2.6.zip",
    ],
)

load("//bazel:preload_grpc.bzl", "preload_grpc")

preload_grpc()

load("//bazel:preload_opentelemetry.bzl", "preload_opentelemetry")

preload_opentelemetry()

http_archive(
    name = "opentelemetry_cpp",
    sha256 = "7735cc56507149686e6019e06f588317099d4522480be5f38a2a09ec69af1706",
    strip_prefix = "opentelemetry-cpp-1.13.0",
    urls = ["https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/thirdparty/github.com/open-telemetry/opentelemetry-cpp/v1.13.0.tar.gz"],
)

load("@opentelemetry_cpp//bazel:repository.bzl", "opentelemetry_cpp_deps")
opentelemetry_cpp_deps()

load("@opentelemetry_cpp//bazel:extra_deps.bzl", "opentelemetry_extra_deps")
opentelemetry_extra_deps()

load("@com_github_grpc_grpc//bazel:grpc_deps.bzl", "grpc_deps")

grpc_deps()
load("//bazel:grpc_extra_deps.bzl", "grpc_extra_deps")
grpc_extra_deps()

http_archive(
    name = "boost",
    build_file = "@//bazel:boost.bzl",
    sha256 = "f55c340aa49763b1925ccf02b2e83f35fdcf634c9d5164a2acb87540173c741d",
    strip_prefix = "boost_1_87_0",
    url = "https://archives.boost.io/release/1.87.0/source/boost_1_87_0.tar.gz",
)

# Pre-built Boost libraries for macOS (static libraries built separately)
new_local_repository(
    name = "boost_libs",
    path = "thirdparty/boost",
    build_file = "@//bazel:boost_libs.BUILD",
)

http_archive(
    name = "msgpack",
    build_file = "@//bazel:msgpack.bzl",
    sha256 = "b68cf63b0bc1d1a84e81252ed44c60528eb60670e81518428804d3d36da57621",
    strip_prefix = "msgpack-c-cpp-5.0.0",
    url = "https://github.com/msgpack/msgpack-c/archive/refs/tags/cpp-5.0.0.zip",
)

http_archive(
    name = "yaml-cpp",
    sha256 = "fbe74bbdcee21d656715688706da3c8becfd946d92cd44705cc6098bb23b3a16",
    strip_prefix = "yaml-cpp-0.8.0",
    urls = [
        "https://github.com/jbeder/yaml-cpp/archive/refs/tags/0.8.0.tar.gz",
    ],
    build_file = "@//bazel:yaml_cpp.BUILD",
)

# DataSystem SDK - use stub targets on macOS where the native SDK is disabled
platform_local_repository(
    name = "datasystem_sdk",
    build_file = "@//bazel:datasystem_build.bzl",
    path = "datasystem",
    stub_build_file = "@//bazel:stub_datasystem.bzl",
)

# DataSystem SDK source build external dependencies
load("@host_platform//:defs.bzl", "IS_MACOS")
load("//bazel:maybe_datasystem_deps.bzl", "maybe_datasystem_deps")

maybe_datasystem_deps(not IS_MACOS)

load("@bazel_tools//tools/jdk:remote_java_repository.bzl", "remote_java_repository")

http_archive(
    name = "remote_java_tools",
    sha256 = "5cd59ea6bf938a1efc1e11ea562d37b39c82f76781211b7cd941a2346ea8484d",
    url = "https://mirror.bazel.build/bazel_java_tools/releases/java/v11.9/java_tools-v11.9.zip",
    patches = ["@yuanrong_multi_language_runtime//patch:remote_java_tools.patch"],
)

http_archive(
    name = "remote_java_tools_linux",
    sha256 = "512582cac5b7ea7974a77b0da4581b21f546c9478f206eedf54687eeac035989",
    urls = [
        "https://mirror.bazel.build/bazel_java_tools/releases/java/v11.9/java_tools_linux-v11.9.zip",
    ],
)

http_archive(
    name = "jacoco",
    sha256 = "6859d4deecc9fdd44f742bb8ff8e4ca71afca442cc8ce67aeb668dda951e8498",
    urls = ["https://github.com/jacoco/jacoco/releases/download/v0.8.8/jacoco-0.8.8.zip"],
    build_file = "@//bazel:jacoco.bzl"
)

# Use local securec from thirdparty directory
new_local_repository(
    name = "securec",
    path = "./thirdparty/libboundscheck",
    build_file = "@//bazel:securec.bzl",
)

http_archive(
    name = "gloo",
    build_file = "@//bazel:gloo.bzl",
    sha256 = "ddfb9627304025f294c78fd75ae84d7b9a662213d1b1c955afe6f91bfeb49254",
    strip_prefix = "gloo-main",
    urls = [
        "https://build-logs.openeuler.openatom.cn:38080/temp-archived/openeuler/openYuanrong/deps/gloo-main.zip",
    ],
    patches= [
        "@//patch:gloo-fix-sign-compare.patch",
    ]
)

# etcd source for python package
http_archive(
    name = "etcd_source",
    build_file = "//bazel:etcd.BUILD",
    strip_prefix = "etcd-3.5.24",
    urls = [
        "https://github.com/etcd-io/etcd/archive/refs/tags/v3.5.24.zip",
        "https://gitee.com/mirrors/etcd/repository/archive/v3.5.24.zip",
    ],
)
