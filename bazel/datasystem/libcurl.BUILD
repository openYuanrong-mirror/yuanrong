load("@rules_foreign_cc//foreign_cc:defs.bzl", "cmake")

filegroup(
    name = "all_srcs",
    srcs = glob(["**"]),
)

cmake(
    name = "libcurl",
    lib_source = ":all_srcs",
    cache_entries = {
        "CMAKE_BUILD_TYPE": "Release",
        "BUILD_SHARED_LIBS": "OFF",
        "BUILD_CURL_EXE": "OFF",
        "BUILD_TESTING": "OFF",
        "CURL_USE_OPENSSL": "ON",
        "CURL_DISABLE_LDAP": "ON",
        "CURL_DISABLE_LDAPS": "ON",
    },
    out_static_libs = ["libcurl.a"],
    deps = ["@boringssl//:ssl", "@boringssl//:crypto"],
    visibility = ["//visibility:public"],
)
