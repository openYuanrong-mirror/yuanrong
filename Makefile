.PHONY: help frontend datasystem functionsystem runtime_launcher yuanrong dashboard pkg image all clean

# Bazel remote cache server (optional, can be set via environment variable)
# Example: REMOTE_CACHE=http://192.168.3.45:9090 make yuanrong
REMOTE_CACHE ?=
NPROCS := $(shell nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)
FUNCTIONSYSTEM_JOBS ?= $(shell jobs=$$(($(NPROCS) / 2)); if [ $$jobs -lt 1 ]; then jobs=1; fi; echo $$jobs)

help:
	@echo "Available targets:"
	@echo "  make clean          - Clean build outputs"
	@echo "  make frontend        - Build frontend (auto-fixes go.mod path)"
	@echo "  make datasystem     - Build datasystem"
	@echo "  make functionsystem - Build functionsystem"
	@echo "  make runtime_launcher - Build runtime-launcher"
	@echo "  make yuanrong       - Build runtime"
	@echo "  make dashboard      - Build dashboard"
	@echo "  make pkg           - Copy packages to example/aio/pkg/"
	@echo "  make image         - Build aio images after make all"
	@echo "  make all           - Build all targets and prepare example/aio/pkg/"
	@echo ""
	@echo "Parameters (optional):"
	@echo "  REMOTE_CACHE       - Remote cache server address"
	@echo "                      Example: make yuanrong REMOTE_CACHE=grpc://192.168.3.45:9092"
	@echo "                      If not provided, build will proceed without remote cache"
	@echo "  FUNCTIONSYSTEM_JOBS - Functionsystem jobs (default: auto/2)"
	@echo "                      Example: make functionsystem FUNCTIONSYSTEM_JOBS=8"

clean:
	@echo "Cleaning build outputs..."
	@cd frontend && bash build.sh clean 2>/dev/null || true && cd ..
	@cd datasystem && bash build.sh clean 2>/dev/null || true && cd ..
	@rm -rf functionsystem/output/
	@rm -rf go/output/
	@bash build.sh -C clean 2>/dev/null || true
	@rm -rf output/
	@rm -f functionsystem/vendor/src/yr-datasystem.tar.gz
	@echo "Clean completed!"

frontend:
	@if grep -q 'yuanrong.org/kernel/runtime.*=>.*\.\./yuanrong/api/go' "frontend/go.mod"; then \
		sed -i 's|yuanrong.org/kernel/runtime.*=>.*\.\./yuanrong/api/go|yuanrong.org/kernel/runtime => ../api/go|g' "frontend/go.mod"; \
		echo "Updated frontend/go.mod: yuanrong.org/kernel/runtime => ../api/go"; \
	else \
		echo "frontend/go.mod already correct"; \
	fi
	bash frontend/build.sh
	@mkdir -p output
	@cp frontend/output/yr-frontend*.tar.gz output/

datasystem:
	bash datasystem/build.sh -X off -G on -i on
	@mkdir -p output
	@cp datasystem/output/yr-datasystem*.tar.gz output/
	mkdir -p functionsystem/vendor/src
	cp datasystem/output/yr-datasystem-*.tar.gz functionsystem/vendor/src/yr-datasystem.tar.gz
	[ -d datasystem/output/sdk ] || tar --no-same-owner -zxf datasystem/output/yr-datasystem-*.tar.gz --strip-components=1 -C datasystem/output

runtime_launcher:
	@echo "Building runtime-launcher..."
	@export PATH=/usr/local/go/bin:~/bin:~/go/bin:$$PATH; \
	if ! command -v go >/dev/null 2>&1; then \
		echo "Error: Go not found. Please install Go and add to PATH."; \
		exit 1; \
	fi
	@mkdir -p functionsystem/runtime-launcher/bin
	@echo "Generating protobuf files..."
	@export PATH=/usr/local/go/bin:~/bin:~/go/bin:$$PATH; \
	cd functionsystem/runtime-launcher && \
	protoc --go_out=. --go_opt=paths=source_relative \
		--go-grpc_out=. --go-grpc_opt=paths=source_relative \
		api/proto/runtime/v1/runtime_launcher.proto
	@echo "Compiling runtime-launcher..."
	@export PATH=/usr/local/go/bin:~/bin:~/go/bin:$$PATH; \
	cd functionsystem/runtime-launcher && \
	go build -buildvcs=false -o bin/runtime/runtime-launcher ./cmd/runtime-launcher/ && \
	go build -buildvcs=false -o bin/rl-client ./cmd/rl-client/
	@echo "Runtime-launcher built successfully!"

functionsystem:
	cd functionsystem && bash run.sh build -j $(FUNCTIONSYSTEM_JOBS) && bash run.sh pack && cd -
	cp -ar functionsystem/output/metrics ./
	cp functionsystem/output/yr-functionsystem*.tar.gz output/

dashboard:
	cd go && bash build.sh && cd -
	cp go/output/yr-dashboard*.tar.gz output/
	cp go/output/yr-faas*.tar.gz output/

yuanrong:
	@echo "Building yuanrong runtime..."
ifeq ($(strip $(REMOTE_CACHE)),)
	bash build.sh -P
else
	bash build.sh -P -r $(REMOTE_CACHE)
endif

pkg:
	@echo "Copying packages to example/aio/pkg/..."
	@mkdir -p example/aio/pkg
	@cp datasystem/output/sdk/openyuanrong_datasystem_sdk-*.whl example/aio/pkg/ 2>/dev/null || true
	@cp datasystem/output/openyuanrong_datasystem-*.whl example/aio/pkg/ 2>/dev/null || true
	@cp functionsystem/output/openyuanrong_functionsystem-*.whl example/aio/pkg/ 2>/dev/null || true
	@cp output/openyuanrong-*.whl example/aio/pkg/ 2>/dev/null || true
	@cp output/openyuanrong_sdk-*.whl example/aio/pkg/ 2>/dev/null || true
	@cp functionsystem/runtime-launcher/bin/runtime/runtime-launcher example/aio/pkg/runtime-launcher 2>/dev/null || true
	@mkdir -p example/aio/docs
	@echo "Packages copied successfully!"
	@ls -la example/aio/pkg/

image:
	@echo "Building aio images via example/aio/build-images.sh..."
	@./example/aio/build-images.sh

all: frontend datasystem functionsystem runtime_launcher dashboard yuanrong pkg
	@echo "Build completed!"
	@echo "Artifacts and example/aio/pkg are ready."
