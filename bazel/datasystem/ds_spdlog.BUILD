# ds-spdlog: spdlog v1.12.0 with datasystem namespace (ds_spdlog)
# The namespace patch renames spdlog:: -> ds_spdlog:: and output lib to ds-spdlog
# Since spdlog supports header-only OR compiled mode, we build in compiled mode
# with SPDLOG_COMPILED_LIB defined.

cc_library(
    name = "ds_spdlog",
    srcs = glob(["src/*.cpp"]),
    hdrs = glob([
        "include/**/*.h",
    ]),
    copts = [
        "-fPIC",
        "-std=c++17",
    ],
    local_defines = [
        "SPDLOG_COMPILED_LIB",
    ],
    includes = ["include"],
    visibility = ["//visibility:public"],
)
