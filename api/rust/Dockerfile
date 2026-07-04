# Build stage: use the Rust compile image.
FROM swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev/compile-ubuntu2004-rust:v20260507_x86_64 AS build
WORKDIR /src
COPY . .
RUN cargo build --release -p rrt-daemon

# Runtime stage: keep the same glibc baseline as the build image (Ubuntu 20.04).
FROM swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev/ubuntu:20.04
COPY --from=build /src/target/release/rrt /usr/local/bin/rrt
ENV RRT_LISTEN=0.0.0.0:50088
EXPOSE 50088
ENTRYPOINT ["/usr/local/bin/rrt"]
