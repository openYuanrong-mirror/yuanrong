"""WORKSPACE macro to load DataSystem SDK external dependencies."""

load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

def datasystem_deps():
    """Load all external dependencies required by DataSystem SDK source build."""

    # libsodium v1.0.18 - crypto library, dependency of libzmq
    http_archive(
        name = "ds_libsodium",
        urls = [
            "https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/thirdparty/github.com/jedisct1/libsodium/libsodium-1.0.18.tar.gz",
            "https://github.com/jedisct1/libsodium/releases/download/1.0.18-RELEASE/libsodium-1.0.18.tar.gz",
        ],
        sha256 = "6f504490b342a4f8a4c4a02fc9b866cbef8622d5df4e5452b46be121e46636c1",
        strip_prefix = "libsodium-1.0.18",
        build_file = "@yuanrong_multi_language_runtime//bazel/datasystem:libsodium.BUILD",
    )

    # libzmq v4.3.5 - ZeroMQ messaging library
    http_archive(
        name = "ds_libzmq",
        urls = [
            "https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/thirdparty/github.com/zeromq/libzmq/zeromq-4.3.5.tar.gz",
            "https://github.com/zeromq/libzmq/releases/download/v4.3.5/zeromq-4.3.5.tar.gz",
        ],
        sha256 = "6653ef5910f17954861fe72332e68b03ca6e4d9c7160eb3a8de5a5a913bfab43",
        strip_prefix = "zeromq-4.3.5",
        build_file = "@yuanrong_multi_language_runtime//bazel/datasystem:libzmq.BUILD",
    )

    # Intel TBB v2020.3 - Threading Building Blocks
    http_archive(
        name = "ds_tbb",
        urls = [
            "https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/thirdparty/github.com/oneapi-src/oneTBB/v2020.3.tar.gz",
            "https://github.com/oneapi-src/oneTBB/archive/refs/tags/v2020.3.tar.gz",
        ],
        sha256 = "ebc4f6aa47972daed1f7bf71d100ae5bf6931c2e3144cf299c8cc7d041dca2f3",
        strip_prefix = "oneTBB-2020.3",
        build_file = "@yuanrong_multi_language_runtime//bazel/datasystem:tbb.BUILD",
    )

    # jemalloc v5.3.0 - memory allocator
    # Using release tarball which includes pre-generated configure script
    http_archive(
        name = "ds_jemalloc",
        urls = [
            "https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/thirdparty/github.com/jemalloc/jemalloc/jemalloc-5.3.0.tar.bz2",
            "https://github.com/jemalloc/jemalloc/releases/download/5.3.0/jemalloc-5.3.0.tar.bz2",
        ],
        sha256 = "2db82d1e7119df3e71b7640219b6dfe84789bc0537983c3b7ac4f7189aecfeaa",
        strip_prefix = "jemalloc-5.3.0",
        build_file = "@yuanrong_multi_language_runtime//bazel/datasystem:jemalloc.BUILD",
    )

    # spdlog v1.12.0 with datasystem patches (ds_spdlog namespace)
    http_archive(
        name = "ds_spdlog",
        urls = [
            "https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/thirdparty/github.com/gabime/spdlog/v1.12.0.tar.gz",
            "https://github.com/gabime/spdlog/archive/refs/tags/v1.12.0.tar.gz",
        ],
        sha256 = "4dccf2d10f410c1e2feaff89966bfc49a1abb29ef6f08246335b110e001e09a9",
        strip_prefix = "spdlog-1.12.0",
        build_file = "@yuanrong_multi_language_runtime//bazel/datasystem:ds_spdlog.BUILD",
        patches = [
            "@datasystem_sdk//:third_party/patches/spdlog/change-namespace.patch",
            "@datasystem_sdk//:third_party/patches/spdlog/change-rotating-file-sink.patch",
        ],
        patch_args = ["-p1"],
    )

    # libcurl v8.8.0 - HTTP client library
    http_archive(
        name = "ds_libcurl",
        urls = [
            "https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/thirdparty/github.com/curl/curl/curl-8.8.0.tar.gz",
            "https://github.com/curl/curl/releases/download/curl-8_8_0/curl-8.8.0.tar.gz",
        ],
        sha256 = "77c0e1cd35ab5b45b659645a93b46d660e2d834b231693f7c5a56898c81c19e2",
        strip_prefix = "curl-8.8.0",
        build_file = "@yuanrong_multi_language_runtime//bazel/datasystem:libcurl.BUILD",
        patches = [
            "@datasystem_sdk//:third_party/patches/curl/8.8.0/Backport-CVE-2024-6197-fix-CVE-2024-6197-for-curl-8.8.0-c.patch",
            "@datasystem_sdk//:third_party/patches/curl/8.8.0/Backport-CVE-2024-6874-fix-CVE-2024-6874-for-curl-8.8.0-c.patch",
            "@datasystem_sdk//:third_party/patches/curl/8.8.0/Backport-CVE-2024-7264-fix-CVE-2024-7264-for-curl-8.8.0-c.patch",
            "@datasystem_sdk//:third_party/patches/curl/8.8.0/Backport-CVE-2024-8096-fix-CVE-2024-8096-for-curl-8.8.0-c.patch",
            "@datasystem_sdk//:third_party/patches/curl/8.8.0/Backport-CVE-2024-9681-fix-CVE-2024-9681-for-curl-8.8.0-c.patch",
            "@datasystem_sdk//:third_party/patches/curl/8.8.0/Backport-CVE-2024-11053-fix-CVE-2024-11053-for-curl-8.8.0-c.patch",
            "@datasystem_sdk//:third_party/patches/curl/8.8.0/Backport-CVE-2025-0167-fix-CVE-2025-0167-for-curl-8.8.0-c.patch",
            "@datasystem_sdk//:third_party/patches/curl/8.8.0/Backport-CVE-2025-0725-fix-CVE-2025-0725-for-curl-8.8.0-c.patch",
            "@datasystem_sdk//:third_party/patches/curl/8.8.0/support_old_cmake.patch",
        ],
        patch_args = ["-p1"],
    )
