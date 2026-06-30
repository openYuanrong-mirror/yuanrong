---
name: local-build
description: Use when building YuanRong packages or SDKs across local Linux, remote macOS, and remote Linux ARM environments with environment checks and scripted execution.
---

# 本地构建

这个 skill 只负责告诉你怎么调用脚本。

## 适用场景

- 需要编译 `linux-x86` 包
- 需要编译 `macos-sdk`
- 需要编译 `linux-arm` 包
- 需要统一走“环境检查 -> 选择本地或远端 -> 执行构建 -> 收集产物”的流程

## 调用方式

```bash
bash .skills/local-build/bin/local-build.sh linux-x86
bash .skills/local-build/bin/local-build.sh macos-sdk
bash .skills/local-build/bin/local-build.sh linux-arm
bash .skills/local-build/bin/local-build.sh all
```

调试模式：

```bash
bash .skills/local-build/bin/local-build.sh --dry-run linux-arm
```

## 依赖环境变量

- `YR_LOCAL_BUILD_MAC_HOST`
  - mac-mini 的 SSH 地址
- `YR_LOCAL_BUILD_X86_HOST`
  - 可选
  - 当当前机器不是 `x86_64 Linux` 时，`linux-x86` 的回退构建机器

这些默认值在 `~/.bashrc` 中维护。修改后重新加载：

```bash
source ~/.bashrc
```

## 默认镜像

Linux 构建默认使用下面这个镜像，已经写在脚本默认值里，不要求你再配环境变量：

```bash
swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev/compile-ubuntu2004:v20260409_guaranteed
```

## 行为说明

- `linux-x86`
  - 先检查当前机器是否是 `x86_64 Linux`
  - 是则在当前机器基于镜像拉起或复用容器构建
  - Linux 统一执行 `make all`，编译所有组件
  - 容器内默认映射当前普通用户 `uid:gid` 执行，避免宿主机生成 root 权限文件
  - 否则尝试使用 `YR_LOCAL_BUILD_X86_HOST`
- `macos-sdk`
  - 先检查当前机器是否是 macOS
  - 是则直接在本机编译
  - macOS 统一执行 `bash build.sh`，只产出 SDK wheel
  - 否则走 `YR_LOCAL_BUILD_MAC_HOST`
- `linux-arm`
  - 先检查当前机器是否是 `aarch64/arm64 Linux`
  - 是则在当前机器基于镜像拉起或复用容器构建
  - Linux 统一执行 `make all`，编译所有组件
  - 容器内默认映射对应机器上的普通用户 `uid:gid` 执行，避免远端工作区生成 root 权限文件
  - 否则走 `YR_LOCAL_BUILD_MAC_HOST`，并在远端基于镜像拉起或复用 ARM 容器构建

## 产物位置

脚本会把每个平台的结果收集到：

```bash
output/local-build/<target>/
```

例如：

```bash
output/local-build/linux-x86/
output/local-build/macos-sdk/
output/local-build/linux-arm/
```

## 常见问题

- 提示缺少环境变量：
  - 先执行 `source ~/.bashrc`
  - 再检查 `echo $YR_LOCAL_BUILD_MAC_HOST`、`echo $YR_LOCAL_BUILD_X86_HOST` 是否符合预期
- 提示当前机器平台不匹配：
  - 这是正常保护逻辑
  - 给脚本补充对应远端环境变量即可
- 需要更换镜像或远端机器：
  - 远端机器改 `~/.bashrc`
  - 镜像默认值改脚本里的内置默认值
