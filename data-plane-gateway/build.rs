fn main() {
    // etcd-client generates its protobuf bindings in its build script. Keep
    // this crate self-contained in CI and developer containers without a
    // system protoc installation.
    if let Ok(path) = protoc_bin_vendored::protoc_bin_path() {
        std::env::set_var("PROTOC", path);
    }
    tonic_build::configure()
        .build_server(false)
        .compile_protos(&["proto/data_plane_gateway_activity.proto"], &["proto"])
        .expect("compile data plane gateway activity proto");
}
