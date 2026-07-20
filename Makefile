.PHONY: help frontend datasystem functionsystem runtime_launcher yuanrong dashboard rust sandbox-sdk pkg aio image all clean

# Bazel remote cache server (optional, can be set via environment variable)
# Example: REMOTE_CACHE=https://192.0.2.1:9090 make yuanrong
REMOTE_CACHE ?=
NPROCS := $(shell nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)
JOBS ?= $(NPROCS)
FUNCTIONSYSTEM_JOBS ?= 8
DATASYSTEM_PYTHON ?= on
DATASYSTEM_JAVA ?= on
BUILD_VERSION ?=
BUILD_VERSION_ARG := $(if $(BUILD_VERSION),-v $(BUILD_VERSION),)

help:
	@echo "Available targets:"
	@echo "  make clean          - Clean build outputs"
	@echo "  make frontend        - Build frontend (auto-fixes go.mod path)"
	@echo "  make datasystem     - Build datasystem"
	@echo "  make functionsystem - Build functionsystem"
	@echo "  make runtime_launcher - Build runtime-launcher"
	@echo "  make yuanrong       - Build runtime"
	@echo "  make dashboard      - Build dashboard"
	@echo "  make rust           - Build rrt-runtime"
	@echo "  make sandbox-sdk    - Build openyuanrong-sandbox wheel"
	@echo "  make pkg            - Copy packages to example/aio/pkg/"
	@echo "  make aio            - Copy packages and build AIO image"
	@echo "  make image         - Build aio images after make all"
	@echo "  make all           - Build all targets"
	@echo ""
	@echo "Parameters (optional):"
	@echo "  REMOTE_CACHE       - Remote cache server address"
	@echo "                      Example: make yuanrong REMOTE_CACHE=grpc://192.0.2.1:9092"
	@echo "                      If not provided, build will proceed without remote cache"
	@echo "  JOBS               - Default parallelism for datasystem and runtime builds"
	@echo "                      Example: make all JOBS=8"
	@echo "  FUNCTIONSYSTEM_JOBS - Parallelism for functionsystem; defaults to 8"
	@echo "                      Example: make all FUNCTIONSYSTEM_JOBS=6"
	@echo "  DATASYSTEM_JAVA    - Build datasystem Java SDK jar; defaults to on"
	@echo "                      Example: make datasystem DATASYSTEM_JAVA=off"

clean:
	@echo "Cleaning build outputs..."
	@bash frontend/build/clean.sh 2>/dev/null || true
	@cd datasystem && bash build.sh clean 2>/dev/null || true && cd ..
	@rm -rf functionsystem/functionsystem/build
	@rm -rf functionsystem/functionsystem/output
	@rm -rf functionsystem/common/logs/build
	@rm -rf functionsystem/common/logs/output
	@rm -rf functionsystem/common/litebus/build
	@rm -rf functionsystem/common/litebus/output
	@rm -rf functionsystem/common/metrics/build
	@rm -rf functionsystem/common/metrics/output
	@rm -rf functionsystem/vendor/build
	@rm -rf functionsystem/vendor/output
	@rm -rf functionsystem/vendor/src/etcd/bin
	@rm -rf functionsystem/output
	@rm -rf go/output
	@bash build.sh -C 2>/dev/null || true
	@rm -rf output/
	@rm -f functionsystem/vendor/src/yr-datasystem.tar.gz
	@echo "Clean completed!"

frontend:
	@if [ -f "frontend/go.mod" ]; then \
		if grep -q 'yuanrong.org/kernel/runtime.*=>.*\.\./yuanrong/api/go' "frontend/go.mod"; then \
			sed -i 's|yuanrong.org/kernel/runtime.*=>.*\.\./yuanrong/api/go|yuanrong.org/kernel/runtime => ../api/go|g' "frontend/go.mod"; \
			echo "Updated frontend/go.mod: yuanrong.org/kernel/runtime => ../api/go"; \
		else \
			echo "frontend/go.mod already correct"; \
		fi \
	else \
		echo "Warning: frontend/go.mod not found, skipping mod fix"; \
	fi
	@if [ -f "frontend/build.sh" ]; then \
		bash frontend/build.sh; \
	else \
		echo "Error: frontend/build.sh not found!"; \
		exit 1; \
	fi
	@mkdir -p output
	@cp frontend/output/yr-frontend*.tar.gz output/ 2>/dev/null || true

datasystem:
	@rm -rf datasystem/output/*
	bash datasystem/build.sh -X off -P $(DATASYSTEM_PYTHON) -J $(DATASYSTEM_JAVA) -G on -i on -j $(JOBS) $(BUILD_VERSION_ARG)
	@mkdir -p output
	@cp datasystem/output/yr-datasystem-*.tar.gz output/
	@mkdir -p functionsystem/vendor/src
	@cp datasystem/output/yr-datasystem-*.tar.gz functionsystem/vendor/src/yr-datasystem.tar.gz
	@tar --no-same-owner -zxf datasystem/output/yr-datasystem-*.tar.gz --strip-components=1 -C datasystem/output
	@cp datasystem/output/*.whl output/ 2>/dev/null || true
	@true

runtime_launcher:
	@echo "Building runtime-launcher..."
	cd functionsystem && bash run.sh build --component runtime_launcher $(BUILD_VERSION_ARG) && cd -
	@mkdir -p output
	@cp functionsystem/runtime-launcher/bin/runtime/runtime-launcher output/runtime-launcher
	@echo "Runtime-launcher built successfully!"

rust:
	@echo "Building rrt-runtime (Rust sandbox runtime)..."
	@command -v cargo >/dev/null 2>&1 || { echo "Error: cargo not found. Build inside the rust compile image."; exit 1; }
	cd api/rust/rrt-daemon && cargo build --release --bin rrt-runtime
	@mkdir -p output
	@cp api/rust/rrt-daemon/target/release/rrt-runtime output/rrt-runtime
	@echo "rrt-runtime built successfully!"

functionsystem:
	cd functionsystem && bash run.sh build -j $(FUNCTIONSYSTEM_JOBS) $(BUILD_VERSION_ARG) && bash run.sh pack $(BUILD_VERSION_ARG) && cd -
	mkdir -p output
	cp -ar functionsystem/output/metrics ./
	cp functionsystem/output/yr-functionsystem*.tar.gz output/
	cp functionsystem/output/*.whl output/
	cp functionsystem/runtime-launcher/bin/runtime/runtime-launcher output/ 2>/dev/null || true

dashboard:
	cd go && bash build.sh && cd -
	mkdir -p output
	cp go/output/yr-dashboard*.tar.gz output/
	cp go/output/yr-faas*.tar.gz output/

runtime:
	@echo "Building yuanrong runtime..."
	bash build.sh -j $(JOBS) $(BUILD_VERSION_ARG)

yuanrong:
	@echo "Building yuanrong..."
	bash build.sh -P -j $(JOBS) $(BUILD_VERSION_ARG)

image:
	@echo "Building aio images via deploy/sandbox/docker/build-images.sh..."
	@./deploy/sandbox/docker/build-images.sh

sandbox-sdk:
	@echo "Building openyuanrong-sandbox (sandbox-sdk) wheel..."
	@if [ ! -f sandbox-sdk/build.sh ]; then \
		echo "sandbox-sdk submodule not initialized; run: git submodule update --init sandbox-sdk"; \
		exit 1; \
	fi
	@mkdir -p output
	@bash sandbox-sdk/build.sh "$(CURDIR)/output"

pkg:
	@echo "Copying packages to example/aio/pkg/..."
	@mkdir -p example/aio/pkg
	@cp datasystem/output/sdk/openyuanrong_datasystem_sdk-*.whl example/aio/pkg/ 2>/dev/null || true
	@cp datasystem/output/openyuanrong_datasystem-*.whl example/aio/pkg/ 2>/dev/null || true
	@cp functionsystem/output/openyuanrong_functionsystem-*.whl example/aio/pkg/ 2>/dev/null || true
	@cp output/openyuanrong-*.whl example/aio/pkg/ 2>/dev/null || true
	@cp output/openyuanrong_sdk-*.whl example/aio/pkg/ 2>/dev/null || true
	@cp output/openyuanrong_runtime-*.whl example/aio/pkg/ 2>/dev/null || true
	@cp output/openyuanrong_dashboard-*.whl example/aio/pkg/ 2>/dev/null || true
	@cp output/openyuanrong_faas-*.whl example/aio/pkg/ 2>/dev/null || true
	@cp output/openyuanrong_cpp_sdk-*.whl example/aio/pkg/ 2>/dev/null || true
	@cp output/openyuanrong_full-*.whl example/aio/pkg/ 2>/dev/null || true
	@cp functionsystem/runtime-launcher/bin/runtime/runtime-launcher example/aio/pkg/runtime-launcher 2>/dev/null || true
	@mkdir -p example/aio/docs
	@cp example/aio/TRAEFIK_ETCD.md example/aio/docs/ 2>/dev/null || true
	@echo "Packages copied successfully!"
	@ls -la example/aio/pkg/

aio: pkg
	@echo "Building Docker image openyuanrongaio:latest..."
	@cd example/aio && docker build -t openyuanrongaio:latest -f Dockerfile . && cd - || (cd -; exit 1)

all: frontend datasystem functionsystem dashboard yuanrong sandbox-sdk
	@echo "Build completed!"
	@echo "Artifacts are ready under output/."

# Define dependencies for parallel make
functionsystem: datasystem
yuanrong: datasystem
