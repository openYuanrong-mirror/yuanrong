load("@rules_foreign_cc//foreign_cc:defs.bzl", "cmake")

filegroup(
    name = "all_srcs",
    srcs = glob(["**"]),
)

cmake(
    name = "libzmq",
    lib_source = ":all_srcs",
    cache_entries = {
        "CMAKE_BUILD_TYPE": "Release",
        "CMAKE_INSTALL_LIBDIR": "lib",
        "ZMQ_BUILD_TESTS": "OFF",
        "ENABLE_CURVE": "ON",
        "WITH_LIBSODIUM": "ON",
        "WITH_LIBSODIUM_STATIC": "ON",
        "BUILD_SHARED": "OFF",
        "BUILD_STATIC": "ON",
        "WITH_PERF_TOOL": "OFF",
        "WITH_DOCS": "OFF",
    },
    out_lib_dir = "lib",
    out_static_libs = ["libzmq.a"],
    deps = ["@ds_libsodium//:libsodium"],
    visibility = ["//visibility:public"],
)
