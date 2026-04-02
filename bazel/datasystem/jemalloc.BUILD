load("@rules_foreign_cc//foreign_cc:defs.bzl", "configure_make")

filegroup(
    name = "all_srcs",
    srcs = glob(["**"]),
)

configure_make(
    name = "jemalloc",
    lib_source = ":all_srcs",
    configure_options = [
        "--with-jemalloc-prefix=datasystem_",
        "--disable-zone-allocator",
        "--without-export",
        "--disable-shared",
        "--enable-static",
        "--disable-cxx",
        "--enable-stats",
        "--disable-initial-exec-tls",
    ],
    env = {
        "CFLAGS": "-fPIC",
        "CXXFLAGS": "-fPIC",
    },
    out_static_libs = ["libjemalloc.a"],
    visibility = ["//visibility:public"],
)
