# Boost per-library targets
# Source: http_archive pointing to boost_1_87_0.tar.gz
# Provides per-library cc_library targets for fine-grained dependencies.
#
# Note: This configuration provides only headers. The actual boost libraries
# are expected to be pre-compiled in ../thirdparty/boost/lib/

cc_library(
    name = "boost_headers",
    hdrs = glob(["boost/**/*.hpp", "boost/**/*.h", "boost/**/*.ipp"]),
    includes = ["."],
    visibility = ["//visibility:public"],
)

# Placeholder libraries - actual linking happens in runtime_lib via linkopts
cc_library(
    name = "atomic",
    deps = [":boost_headers"],
    visibility = ["//visibility:public"],
)

cc_library(
    name = "context",
    deps = [":boost_headers"],
    visibility = ["//visibility:public"],
)

cc_library(
    name = "fiber",
    deps = [":boost_headers"],
    visibility = ["//visibility:public"],
)

cc_library(
    name = "filesystem",
    deps = [":boost_headers"],
    visibility = ["//visibility:public"],
)

# Backward-compatible aggregate target
cc_library(
    name = "boost",
    deps = [
        ":boost_headers",
        ":atomic",
        ":context",
        ":fiber",
        ":filesystem",
    ],
    visibility = ["//visibility:public"],
)
