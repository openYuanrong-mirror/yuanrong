"""Starlark macros for DataSystem SDK proto compilation and libraries."""

# Proto output goes to gen/datasystem/protos/ to match the include path
# used by datasystem source: #include "datasystem/protos/xxx.pb.h"
_PROTO_OUT_PREFIX = "gen/datasystem/protos"

def _proto_outs(name, zmq = False):
    """Return expected output files for a proto compilation."""
    outs = [
        "{}/{}.pb.h".format(_PROTO_OUT_PREFIX, name),
        "{}/{}.pb.cc".format(_PROTO_OUT_PREFIX, name),
    ]
    if zmq:
        outs += [
            "{}/{}.service.rpc.pb.h".format(_PROTO_OUT_PREFIX, name),
            "{}/{}.service.rpc.pb.cc".format(_PROTO_OUT_PREFIX, name),
            "{}/{}.stub.rpc.pb.h".format(_PROTO_OUT_PREFIX, name),
            "{}/{}.stub.rpc.pb.cc".format(_PROTO_OUT_PREFIX, name),
        ]
    return outs

def ds_proto_gen(name, proto_src, proto_dir = "src/datasystem/protos", zmq = False, extra_proto_deps = []):
    """Generate C++ code from a .proto file.

    Args:
        name: Base name for the proto (e.g., "utils")
        proto_src: Path to the .proto file relative to repository root
        proto_dir: Directory containing all protos (for -I path)
        zmq: If True, also run zmq_plugin to generate RPC stubs
        extra_proto_deps: Additional proto source files needed for imports
    """
    outs = _proto_outs(name, zmq)
    out_dir = "$(@D)/gen/datasystem/protos"

    # Build include path for proto compilation
    # Derive protobuf well-known types include root from descriptor.proto location
    proto_include = """
            PROTO_DIR=$$(dirname $(location {proto_src}))
            # descriptor.proto is at <root>/src/google/protobuf/descriptor.proto
            # We need <root>/src as the include path for protoc
            DESC_PATH=$$(echo $(locations @com_google_protobuf//:well_known_protos) | tr ' ' '\\n' | grep 'descriptor\\.proto$$' | head -1)
            WKT_ROOT=$$(dirname $$(dirname $$(dirname $$DESC_PATH)))
    """.format(proto_src = proto_src)

    if zmq:
        cmd = proto_include + """
            mkdir -p {out_dir} && \
            $(location @com_google_protobuf//:protoc) \
                -I$$PROTO_DIR \
                -I$$WKT_ROOT \
                --cpp_out={out_dir} \
                --zmq_out={out_dir} \
                --plugin=protoc-gen-zmq=$(location :zmq_plugin) \
                $(location {proto_src})
        """.format(proto_src = proto_src, out_dir = out_dir)
        tools = [
            "@com_google_protobuf//:protoc",
            ":zmq_plugin",
        ]
    else:
        cmd = proto_include + """
            mkdir -p {out_dir} && \
            $(location @com_google_protobuf//:protoc) \
                -I$$PROTO_DIR \
                -I$$WKT_ROOT \
                --cpp_out={out_dir} \
                $(location {proto_src})
        """.format(proto_src = proto_src, out_dir = out_dir)
        tools = ["@com_google_protobuf//:protoc"]

    # Filter out the primary proto from extra_proto_deps to avoid duplicates
    filtered_deps = [d for d in extra_proto_deps if d != proto_src]

    native.genrule(
        name = "gen_{}_proto".format(name),
        srcs = [proto_src, "@com_google_protobuf//:well_known_protos"] + filtered_deps,
        outs = outs,
        cmd = cmd,
        tools = tools,
    )

def ds_proto_cc_library(name, proto_name, zmq = False, deps = []):
    """Create a cc_library from generated proto code.

    Args:
        name: Library name (e.g., "utils_protos_client")
        proto_name: Base name matching ds_proto_gen (e.g., "utils")
        zmq: Whether this has ZMQ-generated code
        deps: Additional cc_library deps
    """
    outs = _proto_outs(proto_name, zmq)
    srcs = [f for f in outs if f.endswith(".cc")]
    hdrs = [f for f in outs if f.endswith(".h")]

    # ZMQ-generated stubs include datasystem source headers (e.g. rpc_server_stream_base.h)
    # so they need datasystem_hdrs. This is safe: zmq proto cc_lib -> datasystem_hdrs is OK,
    # the cycle was datasystem_hdrs -> zmq proto cc_lib -> genrule -> zmq_plugin -> datasystem_hdrs.
    # We break it by NOT having datasystem_hdrs depend on ZMQ proto targets.
    all_deps = deps + ["@com_google_protobuf//:protobuf"]
    all_copts = ["-Wno-unused-parameter", "-fPIC"]
    if zmq:
        all_deps = all_deps + [":datasystem_hdrs", ":common_rpc_zmq_client"]
        # ZMQ stubs include datasystem headers which use angle-bracket includes for re2/absl
        all_copts = all_copts + [
            "-isystem", "external/com_googlesource_code_re2",
            "-isystem", "external/com_google_absl",
        ]

    native.cc_library(
        name = name,
        srcs = srcs,
        hdrs = hdrs,
        deps = all_deps,
        copts = all_copts,
        # "gen" allows: #include "datasystem/protos/xxx.pb.h"
        # "gen/datasystem/protos" allows: #include "xxx.pb.h" (for proto cross-refs)
        includes = ["gen", "gen/datasystem/protos"],
        visibility = ["//visibility:public"],
    )
