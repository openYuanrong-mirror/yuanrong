load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")
load("//bazel:grpc_upb_repository.bzl", "grpc_upb_repository")
load("@bazel_tools//tools/build_defs/repo:git.bzl", "git_repository")

def preload_grpc():
    http_archive(
        name = "com_google_absl",
        sha256 = "95e90be7c3643e658670e0dd3c1b27092349c34b632c6e795686355f67eca89f",
        strip_prefix = "abseil-cpp-20240722.0",
        urls = [
            "https://github.com/abseil/abseil-cpp/archive/20240722.0.zip",
        ],
        patches = ["@yuanrong_multi_language_runtime//patch:absl_failure_signal_handler.patch"],
    )

    http_archive(
        name = "com_google_protobuf",
        strip_prefix = "protobuf-3.25.5",
        sha256 = "747e7477cd959878998145626b49d6f1b9d46065f2fe805622ff5702334f7cb7",
        urls = [
            "https://github.com/protocolbuffers/protobuf/archive/v3.25.5.zip",
            "https://github.com/protocolbuffers/protobuf/archive/v3.25.5.zip",
        ],
    )

    http_archive(
        name = "utf8_range",
        strip_prefix = "utf8_range-d863bc33e15cba6d873c878dcca9e6fe52b2f8cb",
        sha256 = "568988b5f7261ca181468dba38849fabf59dd9200fb2ed4b2823da187ef84d8c",
        urls = ["https://github.com/protocolbuffers/utf8_range/archive/d863bc33e15cba6d873c878dcca9e6fe52b2f8cb.zip"],
    )

    http_archive(
        name = "cython",
        urls = [
            "https://github.com/cython/cython/archive/refs/tags/3.0.10.zip",
        ],
        sha256 = "339cf9cc18a8706dd68b24d8930ef0578e47e7d8d1468f8e17b2aeb0d7f81346",
        strip_prefix = "cython-3.0.10",
        build_file = "@com_github_grpc_grpc//third_party:cython.BUILD",
    )

    http_archive(
        name = "zlib",
        strip_prefix = "zlib-1.3.1",
        urls = [
            "https://github.com/madler/zlib/archive/v1.3.1.zip",
        ],
        sha256 = "50b24b47bf19e1f35d2a21ff36d2a366638cdf958219a66f30ce0861201760e6",
        build_file = "@com_google_protobuf//:third_party/zlib.BUILD",
    )

    http_archive(
        name = "com_github_grpc_grpc",
        sha256 = "853b4ff0e1c3e1c4e19f8cc77bbab402981920997716003cea6db9970657f8c9",
        strip_prefix = "grpc-1.65.4",
        urls = ["https://github.com/grpc/grpc/archive/refs/tags/v1.65.4.tar.gz"],
        patches = [
            "@//patch:grpc_1.65.patch",
            "@//patch:grpc_1_65_4_gcc_7_3.patch"
        ]
    )

    grpc_upb_repository(
        name = "upb",
        path = Label("@com_github_grpc_grpc//:WORKSPACE")
    )

    http_archive(
        name = "boringssl",
        sha256 = "7a35bebd0e1eecbc5bf5bbf5eec03e86686c356802b5540872119bd26f84ecc7",
        strip_prefix = "boringssl-16c8d3db1af20fcc04b5190b25242aadcb1fbb30",
        urls = [
            "https://storage.googleapis.com/grpc-bazel-mirror/github.com/google/boringssl/archive/16c8d3db1af20fcc04b5190b25242aadcb1fbb30.tar.gz",
            "https://github.com/google/boringssl/archive/16c8d3db1af20fcc04b5190b25242aadcb1fbb30.tar.gz",
        ],
        patch_cmds = [
            """echo '
filegroup(
    name = "shared",
    srcs = [":ssl", ":crypto"],
    visibility = ["//visibility:public"],
)' >> BUILD""",
        ],
    )

    http_archive(
        name = "com_googlesource_code_re2",
        urls = [
            "https://github.com/google/re2/archive/2024-02-01.zip",
        ],
        sha256 = "7e9ddb9096c92568e7d9bb4a912d7eee74fefdc49112daa57bad3f24e6b18b4f",
        strip_prefix = "re2-2024-02-01",
    )

    http_archive(
        name = "com_google_googleapis",
        url = "https://github.com/googleapis/googleapis/archive/541b1ded4abadcc38e8178680b0677f65594ea6f.zip",
        sha256 = "7ebab01b06c555f4b6514453dc3e1667f810ef91d1d4d2d3aa29bb9fcb40a900",
        strip_prefix = "googleapis-541b1ded4abadcc38e8178680b0677f65594ea6f",
    )

    http_archive(
        name = "com_github_cares_cares",
        urls = [
            "https://github.com/c-ares/c-ares/archive/cares-1_19_1.zip",
            "https://github.com/c-ares/c-ares/archive/cares-1_19_1.zip",
        ],
        sha256 = "edcaac184aff0e6b6eb7b9ede7a55f36c7fc04085d67fecff2434779155dd8ce",
        strip_prefix = "c-ares-cares-1_19_1",
    )
