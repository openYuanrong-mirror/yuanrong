"""Stub DataSystem SDK for macOS builds when ENABLE_DATASYSTEM=false."""

package(default_visibility = ["//visibility:public"])

# Empty cc_library for stub
cc_library(
    name = "lib_datasystem_sdk",
    hdrs = [],
    deps = [],
)

# Empty filegroup for shared libs
filegroup(
    name = "shared",
    srcs = [],
)

# Empty filegroup for headers
filegroup(
    name = "public_hdrs",
    srcs = [],
)
