# Pre-built Boost static libraries for macOS
# These libraries are built separately using the Boost build system

cc_library(
    name = "boost_atomic",
    srcs = ["lib/libboost_atomic.a"],
    visibility = ["//visibility:public"],
)

cc_library(
    name = "boost_context",
    srcs = ["lib/libboost_context.a"],
    visibility = ["//visibility:public"],
)

cc_library(
    name = "boost_fiber",
    srcs = ["lib/libboost_fiber.a"],
    deps = [":boost_context", ":boost_atomic"],
    visibility = ["//visibility:public"],
)

cc_library(
    name = "boost_filesystem",
    srcs = ["lib/libboost_filesystem.a"],
    visibility = ["//visibility:public"],
)

cc_library(
    name = "boost_system",
    srcs = ["lib/libboost_system.a"],
    visibility = ["//visibility:public"],
)

# Aggregate target that provides all pre-built libraries
cc_library(
    name = "boost_libs",
    deps = [
        ":boost_atomic",
        ":boost_context",
        ":boost_fiber",
        ":boost_filesystem",
        ":boost_system",
    ],
    visibility = ["//visibility:public"],
)
