load("@rules_foreign_cc//foreign_cc:defs.bzl", "configure_make")

filegroup(
    name = "all_srcs",
    srcs = glob(["**"]),
)

configure_make(
    name = "libsodium",
    lib_source = ":all_srcs",
    configure_options = [
        "--enable-shared=false",
        "--disable-pie",
    ],
    out_static_libs = ["libsodium.a"],
    visibility = ["//visibility:public"],
)
