# Snapshot 与 Checkpoint

## 概述

支持函数快照和实例 checkpoint 功能，实现函数的暂停、恢复和迁移能力。

## 核心概念

### SnapshotType (SnapType)

快照类型枚举：

| 类型 | 值 | 说明 |
|------|-----|------|
| DUMPSTATE | 0 | 状态导出 |
| SNAPSHOT | 1 | 快照 |

## Proto 接口

### SnapOptions

```protobuf
message SnapOptions {
    SnapType type = 1;        // 快照类型
    int32 ttl = 2;             // TTL（秒）
    bool leaveRunning = 3;      // 快照后是否保持运行
}
```

### SnapStartOptions

```protobuf
message SnapStartOptions {
    SnapType type = 1;
    SchedulingOptions scheduleOpts = 2;
}
```

### PrepareSnapRequest / PrepareSnapResponse

快照准备阶段消息。

```protobuf
message PrepareSnapRequest {}

message PrepareSnapResponse {
    ErrorCode code = 1;
    string message = 2;
}
```

### Checkpoint / Restore

Runtime 服务的 Checkpoint 和 Restore 接口：

```protobuf
message CheckpointRequest {
    string checkpointID = 1;
}

message CheckpointResponse {
    ErrorCode code = 1;
    string message = 2;
    bytes state = 3;
}

message RecoverRequest {
    bytes state = 1;
    map<string, string> createOptions = 2;
}

message RecoverResponse {
    ErrorCode code = 1;
    string message = 2;
}
```

## TTL 参数

快照实例支持 TTL（生存时间）配置：

| 参数 | 说明 | 单位 |
|------|------|------|
| `ttl` | 快照实例存活时间 | 秒 |
| 默认值 | 0 (永久) | - |

超过 TTL 的快照实例会被自动清理。

## 使用场景

### 场景 1：函数冷启动优化

    用户请求 -> 检查快照 -> 存在有效快照 -> Restore -> 直接响应
                                        └── 不存在 -> 冷启动

### 场景 2：实例迁移

    源节点 Snapshot -> 传输快照文件 -> 目标节点 Restore

### 场景 3：实例休眠

    运行中实例 -> Snapshot -> 释放资源 -> 用户请求 -> Restore -> 继续运行

## 实现组件

| 组件 | 职责 |
|------|------|
| FunctionProxy | 快照协调和命令下发 |
| FunctionMaster | 快照任务执行和状态管理 |
| FunctionAgent | 实际文件系统操作 |
| Runtime | 进程级快照实现 |
