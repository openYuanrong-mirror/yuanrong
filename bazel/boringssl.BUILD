"""Custom BUILD file for boringssl with shared libraries filegroup."""

package(default_visibility = ["//visibility:public"])

filegroup(
    name = "shared",
    srcs = select({
        "@platforms//os:macos": [
            ":libssl",
            ":libcrypto",
        ],
        "//conditions:default": [
            ":libssl",
            ":libcrypto",
        ],
    }),
    visibility = ["//visibility:public"],
)

# Aliases for the shared libraries
alias(
    name = "libssl",
    actual = ":ssl",
    visibility = ["//visibility:public"],
)

alias(
    name = "libcrypto",
    actual = ":crypto",
    visibility = ["//visibility:public"],
)
