load("@yuanrong_multi_language_runtime//bazel:datasystem_rules.bzl", "ds_proto_gen", "ds_proto_cc_library")

package(default_visibility = ["//visibility:public"])

# Expose patch files from datasystem submodule for external dependency patches
exports_files([
    "third_party/patches/spdlog/change-namespace.patch",
    "third_party/patches/spdlog/change-rotating-file-sink.patch",
    "third_party/patches/spdlog/change-filename.patch",
    "third_party/patches/curl/8.8.0/Backport-CVE-2024-6197-fix-CVE-2024-6197-for-curl-8.8.0-c.patch",
    "third_party/patches/curl/8.8.0/Backport-CVE-2024-6874-fix-CVE-2024-6874-for-curl-8.8.0-c.patch",
    "third_party/patches/curl/8.8.0/Backport-CVE-2024-7264-fix-CVE-2024-7264-for-curl-8.8.0-c.patch",
    "third_party/patches/curl/8.8.0/Backport-CVE-2024-8096-fix-CVE-2024-8096-for-curl-8.8.0-c.patch",
    "third_party/patches/curl/8.8.0/Backport-CVE-2024-9681-fix-CVE-2024-9681-for-curl-8.8.0-c.patch",
    "third_party/patches/curl/8.8.0/Backport-CVE-2024-11053-fix-CVE-2024-11053-for-curl-8.8.0-c.patch",
    "third_party/patches/curl/8.8.0/Backport-CVE-2025-0167-fix-CVE-2025-0167-for-curl-8.8.0-c.patch",
    "third_party/patches/curl/8.8.0/Backport-CVE-2025-0725-fix-CVE-2025-0725-for-curl-8.8.0-c.patch",
    "third_party/patches/curl/8.8.0/support_old_cmake.patch",
    "third_party/patches/tbb/2020.3/soft-link.patch",
])

# ============================================================================
# Include paths: datasystem uses include/ for public headers and src/ for internal
# ============================================================================

DATASYSTEM_COPTS = [
    "-fPIC",
    "-std=c++17",
    "-Wno-unused-parameter",
    "-Wno-sign-compare",
    "-Wno-float-equal",
    "-Wno-comment",
    "-DDATASYSTEM_VERSION=\\\"0.0.0-dev\\\"",
    "-DGIT_HASH=\\\"bazel-build\\\"",
    "-DGIT_BRANCH=\\\"bazel-build\\\"",
    # Some datasystem headers use angle-bracket includes for deps
    # that Bazel only provides via -iquote. Add them as -isystem.
    "-isystem", "external/com_googlesource_code_re2",
    "-isystem", "external/com_google_absl",
]

DATASYSTEM_INCLUDES = [
    "include",
    "src",
]

# Public API headers from include/ directory - depended on by all libs needing
# #include "datasystem/..." paths from the include/ tree
cc_library(
    name = "public_hdrs",
    hdrs = glob(["include/**/*.h"]),
    includes = ["include"],
    visibility = ["//visibility:public"],
)

# ============================================================================
# Section 1: Standard proto compilation (no zmq_plugin needed)
# ============================================================================

PROTO_DIR = "src/datasystem/protos"
PROTO_SRCS = glob(["src/datasystem/protos/*.proto"])

ds_proto_gen(
    name = "utils",
    proto_src = "src/datasystem/protos/utils.proto",
    extra_proto_deps = [],
)

ds_proto_gen(
    name = "meta_zmq",
    proto_src = "src/datasystem/protos/meta_zmq.proto",
    extra_proto_deps = ["src/datasystem/protos/utils.proto"],
)

ds_proto_gen(
    name = "rpc_option",
    proto_src = "src/datasystem/protos/rpc_option.proto",
    extra_proto_deps = [],
)

ds_proto_gen(
    name = "hash_ring",
    proto_src = "src/datasystem/protos/hash_ring.proto",
    extra_proto_deps = [],
)

ds_proto_gen(
    name = "meta_transport",
    proto_src = "src/datasystem/protos/meta_transport.proto",
    extra_proto_deps = ["src/datasystem/protos/utils.proto"],
)

ds_proto_gen(
    name = "p2p_subscribe",
    proto_src = "src/datasystem/protos/p2p_subscribe.proto",
    extra_proto_deps = ["src/datasystem/protos/utils.proto"],
)

# Proto cc_libraries (standard - no ZMQ stubs)
ds_proto_cc_library(
    name = "utils_protos",
    proto_name = "utils",
)

ds_proto_cc_library(
    name = "utils_protos_client",
    proto_name = "utils",
)

ds_proto_cc_library(
    name = "zmq_meta_protos",
    proto_name = "meta_zmq",
    deps = [":utils_protos"],
)

ds_proto_cc_library(
    name = "zmq_meta_protos_client",
    proto_name = "meta_zmq",
    deps = [":utils_protos_client"],
)

ds_proto_cc_library(
    name = "rpc_option_protos",
    proto_name = "rpc_option",
)

ds_proto_cc_library(
    name = "hash_ring_protos",
    proto_name = "hash_ring",
)

ds_proto_cc_library(
    name = "hash_ring_protos_client",
    proto_name = "hash_ring",
)

ds_proto_cc_library(
    name = "meta_transport_protos",
    proto_name = "meta_transport",
    deps = [":utils_protos"],
)

ds_proto_cc_library(
    name = "meta_transport_protos_client",
    proto_name = "meta_transport",
    deps = [":utils_protos_client"],
)

ds_proto_cc_library(
    name = "p2p_subscribe_protos",
    proto_name = "p2p_subscribe",
    deps = [":utils_protos"],
)

ds_proto_cc_library(
    name = "p2p_subscribe_protos_client",
    proto_name = "p2p_subscribe",
    deps = [":utils_protos_client"],
)

# ============================================================================
# Section 2: ZMQ protoc plugin binary
# ============================================================================

# Header-only dependency providing include paths for datasystem sources
cc_library(
    name = "datasystem_hdrs",
    hdrs = glob([
        "src/**/*.h",
        "src/**/*.def",
        "include/**/*.h",
    ]),
    includes = ["src", "include"],
    copts = DATASYSTEM_COPTS,
    deps = [
        "@securec//:securec",
        "@nlohmann_json//:nlohmann_json",
        "@ds_libzmq//:libzmq",
        "@ds_spdlog//:ds_spdlog",
        "@ds_tbb//:tbb",
        "@com_google_protobuf//:protobuf",
        "@com_google_protobuf//:protoc_lib",
        "@com_github_grpc_grpc//:grpc++",
        "@boringssl//:ssl",
        "@boringssl//:crypto",
        "@com_googlesource_code_re2//:re2",
        "@zlib//:zlib",
        "@com_google_absl//absl/debugging:symbolize",
        "@com_google_absl//absl/debugging:failure_signal_handler",
        # Standard proto libraries only (no ZMQ protos - avoids cycle with zmq_plugin)
        ":utils_protos",
        ":zmq_meta_protos",
        ":rpc_option_protos",
        ":hash_ring_protos",
        ":meta_transport_protos_client",
        ":p2p_subscribe_protos",
        ":etcdapi_proto",
    ],
)

cc_binary(
    name = "zmq_plugin",
    srcs = [
        "src/datasystem/common/rpc/plugin_generator/zmq_plugin.cpp",
        "src/datasystem/common/rpc/plugin_generator/zmq_rpc_generator.cpp",
        "src/datasystem/common/rpc/plugin_generator/zmq_rpc_generator.h",
        "src/datasystem/common/rpc/plugin_generator/service_cpp_generator.cpp",
        "src/datasystem/common/rpc/plugin_generator/service_header_generator.cpp",
        "src/datasystem/common/rpc/plugin_generator/stub_cpp_generator.cpp",
        "src/datasystem/common/rpc/plugin_generator/stub_header_generator.cpp",
    ],
    copts = DATASYSTEM_COPTS,
    deps = [
        "@com_google_protobuf//:protobuf",
        "@com_google_protobuf//:protoc_lib",
        ":utils_protos",
        ":zmq_meta_protos",
        ":rpc_option_protos",
        ":datasystem_hdrs",
    ],
)

# ============================================================================
# Section 3: ZMQ proto compilation (needs zmq_plugin)
# ============================================================================

ds_proto_gen(
    name = "share_memory",
    proto_src = "src/datasystem/protos/share_memory.proto",
    zmq = True,
    extra_proto_deps = PROTO_SRCS,
)

ds_proto_gen(
    name = "object_posix",
    proto_src = "src/datasystem/protos/object_posix.proto",
    zmq = True,
    extra_proto_deps = PROTO_SRCS,
)

ds_proto_gen(
    name = "stream_posix",
    proto_src = "src/datasystem/protos/stream_posix.proto",
    zmq = True,
    extra_proto_deps = PROTO_SRCS,
)

ds_proto_gen(
    name = "worker_object",
    proto_src = "src/datasystem/protos/worker_object.proto",
    zmq = True,
    extra_proto_deps = PROTO_SRCS,
)

ds_proto_gen(
    name = "worker_stream",
    proto_src = "src/datasystem/protos/worker_stream.proto",
    zmq = True,
    extra_proto_deps = PROTO_SRCS,
)

ds_proto_gen(
    name = "master_object",
    proto_src = "src/datasystem/protos/master_object.proto",
    zmq = True,
    extra_proto_deps = PROTO_SRCS,
)

ds_proto_gen(
    name = "master_stream",
    proto_src = "src/datasystem/protos/master_stream.proto",
    zmq = True,
    extra_proto_deps = PROTO_SRCS,
)

# ZMQ proto cc_libraries (client variants)
ds_proto_cc_library(
    name = "share_memory_protos_client",
    proto_name = "share_memory",
    zmq = True,
    deps = [":zmq_meta_protos_client"],
)

ds_proto_cc_library(
    name = "posix_protos_client",
    proto_name = "object_posix",
    zmq = True,
    deps = [":zmq_meta_protos_client", ":utils_protos_client", ":p2p_subscribe_protos_client", ":rpc_option_protos"],
)

# stream_posix is merged into posix_protos_client in the cmake build
# but we need separate targets for the genrule outputs
cc_library(
    name = "stream_posix_protos_client",
    srcs = [
        "gen/datasystem/protos/stream_posix.pb.cc",
        "gen/datasystem/protos/stream_posix.service.rpc.pb.cc",
        "gen/datasystem/protos/stream_posix.stub.rpc.pb.cc",
    ],
    hdrs = [
        "gen/datasystem/protos/stream_posix.pb.h",
        "gen/datasystem/protos/stream_posix.service.rpc.pb.h",
        "gen/datasystem/protos/stream_posix.stub.rpc.pb.h",
    ],
    copts = [
        "-Wno-unused-parameter", "-fPIC",
        "-isystem", "external/com_googlesource_code_re2",
        "-isystem", "external/com_google_absl",
    ],
    includes = ["gen", "gen/datasystem/protos"],
    deps = [
        "@com_google_protobuf//:protobuf",
        ":zmq_meta_protos_client",
        ":utils_protos_client",
        ":rpc_option_protos",
        ":datasystem_hdrs",
        ":common_rpc_zmq_client",
    ],
)

ds_proto_cc_library(
    name = "worker_object_protos_client",
    proto_name = "worker_object",
    zmq = True,
    deps = [
        ":zmq_meta_protos_client",
        ":hash_ring_protos_client",
        ":meta_transport_protos_client",
        ":utils_protos_client",
        ":rpc_option_protos",
        ":posix_protos_client",
        ":p2p_subscribe_protos_client",
    ],
)

ds_proto_cc_library(
    name = "worker_stream_protos_client",
    proto_name = "worker_stream",
    zmq = True,
    deps = [
        ":zmq_meta_protos_client",
        ":utils_protos_client",
        ":stream_posix_protos_client",
    ],
)

ds_proto_cc_library(
    name = "master_object_protos_client",
    proto_name = "master_object",
    zmq = True,
    deps = [
        ":posix_protos_client",
        ":worker_object_protos_client",
        ":utils_protos_client",
        ":rpc_option_protos",
        ":p2p_subscribe_protos_client",
    ],
)

ds_proto_cc_library(
    name = "master_stream_protos_client",
    proto_name = "master_stream",
    zmq = True,
    deps = [
        ":worker_stream_protos_client",
        ":utils_protos_client",
        ":rpc_option_protos",
    ],
)

# Convenience target: all ZMQ proto cc_libraries bundled together.
# Used by cc_libraries whose .cpp files transitively include ZMQ-generated headers.
# Cannot be added to datasystem_hdrs (would create cycle through zmq_plugin).
cc_library(
    name = "zmq_protos_all",
    deps = [
        ":share_memory_protos_client",
        ":posix_protos_client",
        ":stream_posix_protos_client",
        ":worker_object_protos_client",
        ":worker_stream_protos_client",
        ":master_object_protos_client",
        ":master_stream_protos_client",
    ],
)

# ============================================================================
# Section 4: etcd protos (standard protobuf + gRPC)
# ============================================================================

ETCD_PROTO_DIR = "third_party/protos"

genrule(
    name = "gen_etcd_protos",
    srcs = glob(["third_party/protos/**/*.proto"]) + ["@com_google_protobuf//:well_known_protos"],
    outs = [
        # gogoproto
        "gen/etcd/gogoproto/gogo.pb.h",
        "gen/etcd/gogoproto/gogo.pb.cc",
        # google/api
        "gen/etcd/google/api/http.pb.h",
        "gen/etcd/google/api/http.pb.cc",
        "gen/etcd/google/api/annotations.pb.h",
        "gen/etcd/google/api/annotations.pb.cc",
        # etcd/api
        "gen/etcd/etcd/api/authpb/auth.pb.h",
        "gen/etcd/etcd/api/authpb/auth.pb.cc",
        "gen/etcd/etcd/api/mvccpb/kv.pb.h",
        "gen/etcd/etcd/api/mvccpb/kv.pb.cc",
        "gen/etcd/etcd/api/etcdserverpb/rpc.pb.h",
        "gen/etcd/etcd/api/etcdserverpb/rpc.pb.cc",
        "gen/etcd/etcd/api/etcdserverpb/rpc.grpc.pb.h",
        "gen/etcd/etcd/api/etcdserverpb/rpc.grpc.pb.cc",
        # etcd top-level
        "gen/etcd/etcd/etcdserver.pb.h",
        "gen/etcd/etcd/etcdserver.pb.cc",
        "gen/etcd/etcd/v3lock.pb.h",
        "gen/etcd/etcd/v3lock.pb.cc",
        "gen/etcd/etcd/v3lock.grpc.pb.h",
        "gen/etcd/etcd/v3lock.grpc.pb.cc",
        "gen/etcd/etcd/v3election.pb.h",
        "gen/etcd/etcd/v3election.pb.cc",
        "gen/etcd/etcd/v3election.grpc.pb.h",
        "gen/etcd/etcd/v3election.grpc.pb.cc",
    ],
    cmd = """
        PROTO_DIR=$$(dirname $$(dirname $(location third_party/protos/gogoproto/gogo.proto)))
        # Derive protobuf well-known types include root from descriptor.proto location
        DESC_PATH=$$(echo $(locations @com_google_protobuf//:well_known_protos) | tr ' ' '\\n' | grep 'descriptor\\.proto$$' | head -1)
        WKT_ROOT=$$(dirname $$(dirname $$(dirname $$DESC_PATH)))
        OUT_DIR=$(@D)/gen/etcd
        mkdir -p $$OUT_DIR/gogoproto $$OUT_DIR/google/api $$OUT_DIR/etcd/api/authpb $$OUT_DIR/etcd/api/mvccpb $$OUT_DIR/etcd/api/etcdserverpb $$OUT_DIR/etcd
        PROTOC=$(location @com_google_protobuf//:protoc)
        GRPC_PLUGIN=$(location @com_github_grpc_grpc//src/compiler:grpc_cpp_plugin)
        # Compile all proto files
        for proto in $(locations third_party/protos/gogoproto/gogo.proto) \
                     $(locations third_party/protos/google/api/http.proto) \
                     $(locations third_party/protos/google/api/annotations.proto) \
                     $(locations third_party/protos/etcd/api/authpb/auth.proto) \
                     $(locations third_party/protos/etcd/api/mvccpb/kv.proto) \
                     $(locations third_party/protos/etcd/etcdserver.proto); do
            $$PROTOC -I$$PROTO_DIR -I$$WKT_ROOT --cpp_out=$$OUT_DIR $$proto
        done
        # Compile gRPC protos
        for proto in $(locations third_party/protos/etcd/api/etcdserverpb/rpc.proto) \
                     $(locations third_party/protos/etcd/v3lock.proto) \
                     $(locations third_party/protos/etcd/v3election.proto); do
            $$PROTOC -I$$PROTO_DIR -I$$WKT_ROOT --cpp_out=$$OUT_DIR --grpc_out=$$OUT_DIR --plugin=protoc-gen-grpc=$$GRPC_PLUGIN $$proto
        done
    """,
    tools = [
        "@com_google_protobuf//:protoc",
        "@com_github_grpc_grpc//src/compiler:grpc_cpp_plugin",
    ],
)

cc_library(
    name = "etcdapi_proto",
    srcs = [
        "gen/etcd/gogoproto/gogo.pb.cc",
        "gen/etcd/google/api/http.pb.cc",
        "gen/etcd/google/api/annotations.pb.cc",
        "gen/etcd/etcd/api/authpb/auth.pb.cc",
        "gen/etcd/etcd/api/mvccpb/kv.pb.cc",
        "gen/etcd/etcd/api/etcdserverpb/rpc.pb.cc",
        "gen/etcd/etcd/api/etcdserverpb/rpc.grpc.pb.cc",
        "gen/etcd/etcd/etcdserver.pb.cc",
        "gen/etcd/etcd/v3lock.pb.cc",
        "gen/etcd/etcd/v3lock.grpc.pb.cc",
        "gen/etcd/etcd/v3election.pb.cc",
        "gen/etcd/etcd/v3election.grpc.pb.cc",
    ],
    hdrs = [
        "gen/etcd/gogoproto/gogo.pb.h",
        "gen/etcd/google/api/http.pb.h",
        "gen/etcd/google/api/annotations.pb.h",
        "gen/etcd/etcd/api/authpb/auth.pb.h",
        "gen/etcd/etcd/api/mvccpb/kv.pb.h",
        "gen/etcd/etcd/api/etcdserverpb/rpc.pb.h",
        "gen/etcd/etcd/api/etcdserverpb/rpc.grpc.pb.h",
        "gen/etcd/etcd/etcdserver.pb.h",
        "gen/etcd/etcd/v3lock.pb.h",
        "gen/etcd/etcd/v3lock.grpc.pb.h",
        "gen/etcd/etcd/v3election.pb.h",
        "gen/etcd/etcd/v3election.grpc.pb.h",
    ],
    copts = ["-Wno-unused-parameter", "-fPIC"],
    includes = ["gen/etcd"],
    deps = [
        "@com_google_protobuf//:protobuf",
        "@com_github_grpc_grpc//:grpc++",
    ],
)

# ============================================================================
# Section 5: Common libraries (bottom-up dependency order)
# ============================================================================

# --- Level 0: No internal deps ---

cc_library(
    name = "ds_flags",
    srcs = [
        "src/datasystem/common/flags/flag_manager.cpp",
        "src/datasystem/common/flags/flags.cpp",
    ],
    hdrs = glob(["src/datasystem/common/flags/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [":datasystem_hdrs"],
)

cc_library(
    name = "common_signal",
    srcs = ["src/datasystem/common/signal/signal.cpp"],
    hdrs = glob(["src/datasystem/common/signal/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [":datasystem_hdrs"],
)

cc_library(
    name = "common_perf",
    srcs = ["src/datasystem/common/perf/perf_manager.cpp"],
    hdrs = glob(["src/datasystem/common/perf/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        "@nlohmann_json//:nlohmann_json",
        ":datasystem_hdrs",
    ],
)

cc_library(
    name = "common_inject",
    srcs = ["src/datasystem/common/inject/inject_point.cpp"],
    hdrs = glob(["src/datasystem/common/inject/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [":datasystem_hdrs"],
)

cc_library(
    name = "common_parallel",
    srcs = glob(["src/datasystem/common/parallel/**/*.cpp"]),
    hdrs = glob(["src/datasystem/common/parallel/**/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [":datasystem_hdrs"],
)

cc_library(
    name = "common_rdma_util",
    srcs = [
        "src/datasystem/common/rdma/rdma_util.cpp",
        "src/datasystem/common/rdma/fast_transport_manager_wrapper.cpp",
    ],
    hdrs = glob(["src/datasystem/common/rdma/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    linkopts = select({
        "@platforms//os:linux": ["-ldl"],
        "//conditions:default": [],
    }),
    deps = [":datasystem_hdrs"],
)

cc_library(
    name = "metrics_exporter_base",
    srcs = ["src/datasystem/common/metrics/metrics_exporter.cpp"],
    hdrs = glob(["src/datasystem/common/metrics/*.h", "src/datasystem/common/metrics/**/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [":datasystem_hdrs"],
)

cc_library(
    name = "hard_disk_exporter",
    srcs = ["src/datasystem/common/metrics/hard_disk_exporter/hard_disk_exporter.cpp"],
    hdrs = glob(["src/datasystem/common/metrics/hard_disk_exporter/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":metrics_exporter_base",
        ":datasystem_hdrs",
    ],
)

# --- Level 1: ds_spdlog integration ---

cc_library(
    name = "ds_spdlog_lib",
    srcs = glob(["src/datasystem/common/log/spdlog/*.cpp"]),
    hdrs = glob(["src/datasystem/common/log/spdlog/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        "@ds_spdlog//:ds_spdlog",
        "@nlohmann_json//:nlohmann_json",
        ":ds_flags",
        ":common_perf",
        ":datasystem_hdrs",
    ],
)

cc_library(
    name = "common_log",
    srcs = [
        "src/datasystem/common/log/log_manager.cpp",
        "src/datasystem/common/log/logging.cpp",
        "src/datasystem/common/log/access_recorder.cpp",
        "src/datasystem/common/log/trace.cpp",
        "src/datasystem/common/log/failure_handler.cpp",
    ],
    hdrs = glob(["src/datasystem/common/log/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":ds_flags",
        ":ds_spdlog_lib",
        ":hard_disk_exporter",
        "@com_google_absl//absl/debugging:symbolize",
        "@com_google_absl//absl/debugging:failure_signal_handler",
        ":datasystem_hdrs",
    ],
    linkopts = ["-lpthread"],
)

# --- Level 2: common_util and friends ---


cc_library(
    name = "common_util_gflag",
    srcs = glob(["src/datasystem/common/util/gflag/*.cpp"]),
    hdrs = glob(["src/datasystem/common/util/gflag/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_log",
        ":common_inject",
        "@securec//:securec",
        ":datasystem_hdrs",
    ],
)

cc_library(
    name = "common_util_queue",
    srcs = glob(["src/datasystem/common/util/queue/*.cpp"]),
    hdrs = glob(["src/datasystem/common/util/queue/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_log",
        ":common_inject",
        "@securec//:securec",
        ":datasystem_hdrs",
    ],
)

cc_library(
    name = "common_util",
    srcs = glob(
        ["src/datasystem/common/util/*.cpp"],
        exclude = ["src/datasystem/common/util/gflag/*.cpp", "src/datasystem/common/util/queue/*.cpp"],
    ),
    hdrs = glob(
        ["src/datasystem/common/util/*.h"],
        exclude = ["src/datasystem/common/util/gflag/*.h", "src/datasystem/common/util/queue/*.h"],
    ),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_log",
        ":common_inject",
        ":common_util_gflag",
        ":common_util_queue",
        ":common_rdma_util",
        "@securec//:securec",
        "@boringssl//:ssl",
        "@boringssl//:crypto",
        "@com_googlesource_code_re2//:re2",
        "@zlib//:zlib",
        ":datasystem_hdrs",
    ],
    linkopts = select({
        "@platforms//os:linux": ["-lpthread", "-ldl"],
        "//conditions:default": ["-lpthread"],
    }),
)

# --- Level 3: Libraries depending on common_util ---

cc_library(
    name = "token",
    srcs = ["src/datasystem/common/agc/client_access_token.cpp"],
    hdrs = glob(["src/datasystem/common/agc/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_util",
        "@securec//:securec",
        ":datasystem_hdrs",
    ],
)

cc_library(
    name = "ak_sk_signature",
    srcs = [
        "src/datasystem/common/ak_sk/hasher.cpp",
        "src/datasystem/common/ak_sk/signature.cpp",
    ],
    hdrs = glob(["src/datasystem/common/ak_sk/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_util",
        ":common_log",
        "@boringssl//:ssl",
        "@boringssl//:crypto",
        ":datasystem_hdrs",
    ],
)

cc_library(
    name = "common_event_loop",
    srcs = glob(["src/datasystem/common/eventloop/*.cpp"]),
    hdrs = glob(["src/datasystem/common/eventloop/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_util",
        ":common_log",
        "@securec//:securec",
        ":datasystem_hdrs",
    ],
)

cc_library(
    name = "common_immutable_string",
    srcs = glob(["src/datasystem/common/immutable_string/*.cpp"]),
    hdrs = glob(["src/datasystem/common/immutable_string/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_log",
        "@ds_tbb//:tbb",
        ":datasystem_hdrs",
    ],
)

cc_library(
    name = "string_ref",
    srcs = glob(["src/datasystem/common/string_intern/*.cpp"]),
    hdrs = glob(["src/datasystem/common/string_intern/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_log",
        "@ds_tbb//:tbb",
        ":datasystem_hdrs",
    ],
)

cc_library(
    name = "common_shm_unit_info",
    srcs = ["src/datasystem/common/shared_memory/shm_unit_info.cpp"],
    hdrs = ["src/datasystem/common/shared_memory/shm_unit_info.h"],
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_log",
        ":common_util",
        ":datasystem_hdrs",
    ],
)

cc_library(
    name = "common_shared_memory",
    srcs = glob(
        ["src/datasystem/common/shared_memory/*.cpp", "src/datasystem/common/shared_memory/mmap/*.cpp"],
        exclude = ["src/datasystem/common/shared_memory/shm_unit_info.cpp"],
    ),
    hdrs = glob(["src/datasystem/common/shared_memory/*.h", "src/datasystem/common/shared_memory/mmap/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_perf",
        ":common_shm_unit_info",
        "@ds_jemalloc//:jemalloc",
        ":datasystem_hdrs",
    ],
    linkopts = select({
        "@platforms//os:linux": ["-ldl"],
        "//conditions:default": [],
    }),
)

cc_library(
    name = "common_encrypt_client",
    srcs = [
        "src/datasystem/common/encrypt/encrypt_kit.cpp",
        "src/datasystem/common/encrypt/secret_manager.cpp",
        "src/datasystem/common/encrypt/phrase_pem_tls.cpp",
    ],
    hdrs = glob(["src/datasystem/common/encrypt/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_log",
        ":common_util",
        "@boringssl//:ssl",
        "@boringssl//:crypto",
        ":datasystem_hdrs",
    ],
)

cc_library(
    name = "common_device",
    srcs = [],
    hdrs = glob(["src/datasystem/common/device/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_util",
        ":common_inject",
        ":datasystem_hdrs",
    ],
    linkopts = select({
        "@platforms//os:linux": ["-ldl"],
        "//conditions:default": [],
    }),
    alwayslink = True,
)

# ACL/CUDA device code - vendor SDK headers guarded by BUILD_HETERO (not defined)
# Uses dlopen at runtime, compiled without vendor features
cc_library(
    name = "common_acl_device",
    srcs = glob(["src/datasystem/common/device/ascend/*.cpp"]),
    hdrs = glob(["src/datasystem/common/device/ascend/*.h"]) +
           glob(["src/datasystem/common/device/ascend/plugin/*.h"]) +
           glob(["src/datasystem/common/device/nvidia/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_device",
        ":common_util",
        ":common_inject",
        ":datasystem_hdrs",
    ],
    linkopts = select({
        "@platforms//os:linux": ["-ldl"],
        "//conditions:default": [],
    }),
    # alwayslink ensures PipeLineP2PBase etc. are included even though common_device
    # can't declare a direct dep on common_acl_device (cycle: acl_device -> device -> acl_device)
    alwayslink = True,
)

cc_library(
    name = "common_rdma",
    srcs = glob(
        ["src/datasystem/common/rdma/*.cpp"],
        exclude = [
            "src/datasystem/common/rdma/rdma_util.cpp",
            "src/datasystem/common/rdma/fast_transport_manager_wrapper.cpp",
            # Exclude URMA/UCP/NPU files (need special flags)
            "src/datasystem/common/rdma/urma_*.cpp",
            "src/datasystem/common/rdma/ucp_*.cpp",
            "src/datasystem/common/rdma/npu/*.cpp",
        ],
    ),
    hdrs = glob(["src/datasystem/common/rdma/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_rdma_util",
        ":meta_transport_protos_client",
        ":datasystem_hdrs",
    ],
)

# --- Level 4: RPC client library ---

cc_library(
    name = "common_rpc_zmq_client",
    srcs = [
        "src/datasystem/common/rpc/rpc_auth_key_manager.cpp",
        "src/datasystem/common/rpc/rpc_auth_key_manager_server.cpp",
        "src/datasystem/common/rpc/rpc_channel.cpp",
        "src/datasystem/common/rpc/rpc_message.cpp",
        "src/datasystem/common/rpc/rpc_credential.cpp",
        "src/datasystem/common/rpc/rpc_options.cpp",
        "src/datasystem/common/rpc/rpc_server.cpp",
        "src/datasystem/common/rpc/rpc_service_cfg.cpp",
        "src/datasystem/common/rpc/rpc_auth_keys.cpp",
        "src/datasystem/common/rpc/mem_view.cpp",
        "src/datasystem/common/rpc/unix_sock_fd.cpp",
    ] + glob(["src/datasystem/common/rpc/zmq/*.cpp"]),
    hdrs = glob([
        "src/datasystem/common/rpc/*.h",
        "src/datasystem/common/rpc/zmq/*.h",
    ]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        "@com_google_protobuf//:protobuf",
        "@nlohmann_json//:nlohmann_json",
        "@ds_libzmq//:libzmq",
        "@securec//:securec",
        ":common_log",
        ":common_perf",
        ":common_util",
        ":utils_protos_client",
        ":zmq_meta_protos_client",
        ":datasystem_hdrs",
    ],
    alwayslink = True,
)

# --- Level 5: stream_cache (common_sc) ---

cc_library(
    name = "common_sc",
    srcs = glob(["src/datasystem/common/stream_cache/*.cpp"]),
    hdrs = glob(["src/datasystem/common/stream_cache/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_log",
        ":posix_protos_client",
        ":zmq_protos_all",
        ":datasystem_hdrs",
    ],
)

# --- Level 5: buffer management ---

cc_library(
    name = "common_buffer",
    srcs = glob(["src/datasystem/common/object_cache/*.cpp"]),
    hdrs = glob(["src/datasystem/common/object_cache/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_log",
        ":common_util",
        ":common_shared_memory",
        ":posix_protos_client",
        ":zmq_protos_all",
        "@securec//:securec",
        "@ds_tbb//:tbb",
        ":datasystem_hdrs",
    ],
)

# --- Level 5: etcd client ---

cc_library(
    name = "common_etcd_client",
    srcs = glob(["src/datasystem/common/kvstore/etcd/*.cpp"]),
    hdrs = glob(["src/datasystem/common/kvstore/etcd/*.h"]) +
           glob(["src/datasystem/common/kvstore/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_log",
        ":common_util",
        ":common_signal",
        ":common_encrypt_client",
        ":etcdapi_proto",
        "@com_github_grpc_grpc//:grpc++",
        "@ds_tbb//:tbb",
        ":datasystem_hdrs",
    ],
)

# ============================================================================
# Section 6: Client mmap library
# ============================================================================

cc_library(
    name = "client_mmap_static",
    srcs = glob(["src/datasystem/client/mmap/*.cpp"]),
    hdrs = glob(["src/datasystem/client/mmap/*.h"]),
    copts = DATASYSTEM_COPTS,
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_util",
        ":common_shared_memory",
        "@securec//:securec",
        ":datasystem_hdrs",
    ],
)

# ============================================================================
# Section 7: Client SDK library (libdatasystem)
# ============================================================================

cc_library(
    name = "datasystem_client_lib",
    srcs = glob(
        ["src/datasystem/client/*.cpp", "src/datasystem/client/**/*.cpp"],
        exclude = ["src/datasystem/client/mmap/*.cpp", "src/datasystem/client/perf_client/*.cpp"],
    ),
    hdrs = glob(
        ["src/datasystem/client/*.h", "src/datasystem/client/**/*.h"],
        exclude = ["src/datasystem/client/mmap/*.h"],
    ),
    copts = DATASYSTEM_COPTS + ["-fvisibility=hidden"],
    includes = DATASYSTEM_INCLUDES,
    deps = [
        "@securec//:securec",
        "@ds_tbb//:tbb",
        "@com_google_protobuf//:protobuf",
        "@nlohmann_json//:nlohmann_json",
        ":token",
        ":ak_sk_signature",
        ":common_buffer",
        ":common_event_loop",
        ":common_inject",
        ":common_log",
        ":common_perf",
        ":common_sc",
        ":common_shm_unit_info",
        ":common_util",
        ":common_immutable_string",
        ":string_ref",
        ":common_device",
        ":common_acl_device",
        ":common_shared_memory",
        ":common_rdma",
        ":common_parallel",
        ":common_rpc_zmq_client",
        ":common_encrypt_client",
        ":common_etcd_client",
        ":client_mmap_static",
        ":zmq_protos_all",
        ":datasystem_hdrs",
    ],
    # alwayslink ensures HcclCommMagr etc. are available to common_acl_device
    # symbols (p2phccl_comm_wrapper) that reference back into client code
    alwayslink = True,
    visibility = ["//visibility:public"],
)

# ============================================================================
# Section 8: Router Client library (libds_router_client)
# ============================================================================

cc_library(
    name = "ds_router_client_lib",
    srcs = ["src/datasystem/client/router_client.cpp"],
    hdrs = [],
    copts = DATASYSTEM_COPTS + ["-fvisibility=hidden"],
    includes = DATASYSTEM_INCLUDES,
    deps = [
        ":common_etcd_client",
        ":common_util",
        ":hash_ring_protos_client",
        ":etcdapi_proto",
        ":datasystem_hdrs",
    ],
)

# ============================================================================
# Section 9: Public interface targets (matching pre-built SDK interface)
# ============================================================================

# Main target matching @datasystem_sdk//:lib_datasystem_sdk
cc_library(
    name = "lib_datasystem_sdk",
    hdrs = glob(["include/**/*.h"]),
    includes = ["include"],
    deps = [
        ":datasystem_client_lib",
        ":datasystem_hdrs",
    ],
    alwayslink = True,
    visibility = ["//visibility:public"],
)

# Empty filegroup for shared libraries (not available when building from source)
# Create a dummy file to avoid "expands to no files" error
genrule(
    name = "empty_shared_gen",
    outs = [".empty_shared"],
    cmd = "touch $@",
    visibility = ["//visibility:private"],
)

filegroup(
    name = "shared",
    srcs = [":empty_shared_gen"],
    visibility = ["//visibility:public"],
)
