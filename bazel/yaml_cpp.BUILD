cc_library(
    name = "yaml-cpp",
    srcs = glob([
        "src/*.cpp",
        "src/*.h",
    ]),
    hdrs = glob(["include/yaml-cpp/**/*.h"]),
    copts = [
        "-fPIC",
        "-DYAML_CPP_STATIC_DEFINE",
    ],
    includes = ["include"],
    visibility = ["//visibility:public"],
)
