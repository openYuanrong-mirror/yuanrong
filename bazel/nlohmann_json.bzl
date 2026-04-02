cc_library(
    name = "nlohmann_json",
    srcs = [],
    hdrs = ["single_include/nlohmann/json.hpp"],
    includes = ["single_include", "single_include/nlohmann"],
    copts = [],
    visibility = ["//visibility:public"],
)
