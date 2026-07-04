fn main() -> Result<(), Box<dyn std::error::Error>> {
    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .compile_protos(&["proto/rrt/v1/rrt.proto"], &["proto"])?;
    // RuntimeRPC protocol plus MetaData; compile once to avoid duplicate package definitions.
    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .compile_protos(
            &[
                "proto/posix/runtime_rpc.proto",
                "proto/posix/resource.proto",
            ],
            &["proto/posix"],
        )?;
    Ok(())
}
