# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

openYuanrong is a Serverless distributed computing engine that supports AI, big data, and microservices applications with a unified architecture. It provides multi-language function programming interfaces (Python, Java, C++, Go) with single-machine programming experience for distributed applications.

## Build Commands

### Primary Build System (Bazel)

```bash
# Build all API packages (cpp, java, python, go)
bash build.sh

# Build specific language
bash build.sh //api/cpp:yr_cpp_pkg
bash build.sh //api/java:yr_java_pkg
bash build.sh //api/python:yr_python_pkg
bash build.sh //api/go:yr_go_pkg

# Run tests
bash build.sh -t

# Build with debug mode
bash build.sh -D

# Coverage
bash build.sh -c

# Clean build environment
bash build.sh -C
```

### Convenient Build (Makefile)

```bash
make help           # Show available targets
make all            # Build all components
make frontend       # Build frontend
make datasystem     # Build datasystem
make functionsystem # Build functionsystem
make yuanrong       # Build runtime
make dashboard      # Build dashboard (Go)
```

## Architecture

```
api/          - Multi-language SDKs (cpp, java, go, python)
src/          - Core C++ runtime (libruntime, proto, dto, scene, utility)
go/           - Go components (cmd, pkg, proto)
datasystem/   - Data system (distributed cache with Object/Stream semantics)
functionsystem/ - Function system (dynamic scheduling, scaling)
frontend/     - Gateway (HTTP API for function management)
```

## Key Notes

- This repo is the **runtime** component (yuanrong)
- Other components: yuanrong-functionsystem, yuanrong-datasystem, yuanrong-frontend are separate repos
- The Makefile orchestrates building all components in correct dependency order
- Build outputs are copied to `output/` directory
- Development typically requires the datasystem output first (provides SDK)
