# Quota 配额管理系统

## 概述

> **TODO**: 与 IAM 对接调通，实现配额查询和同步

Quota 配额管理系统实现租户级资源配额管理，支持使用量追踪、LIFO 驱逐策略和配额超限冷却机制。

## 核心组件

### QuotaManagerActor

资源配额管理核心 Actor，负责：

- 维护每个租户的配额使用量
- LIFO（后进先出）驱逐策略
- 配额超限冷却通知

### QuotaConfig

配额配置管理，支持 JSON 文件加载：

```json
{
  "quotas": {
    "tenant-a": {
      "max_instances": 100,
      "max_cpu": 1000,
      "max_memory_mb": 102400
    }
  }
}
```

- 维护每个租户的配额使用量

## 接口说明

### 启动参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `--quota_config_file` | string | 配额配置文件路径，为空则禁用配额 enforcement |

### Proto 消息

#### TenantQuotaExceeded

配额超限消息，用于调度拦截通知。

```protobuf
message TenantQuotaExceeded {
    string tenant_id = 1;
    string reason = 2;
    int64 cooldown_ms = 3;
}
```

### 内部接口

| 接口 | 组件 | 说明 |
|------|------|------|
| `InstanceCtrlActor::Schedule()` | InstanceCtrlActor | 配额冷却拦截点 |
| `DomainSchedSrvActor::ForwardQuotaExceeded()` | DomainSchedSrvActor | 转发配额超限消息 |
| `QuotaManagerActor::TrackUsage()` | QuotaManagerActor | 追踪租户使用量 |
| `QuotaManagerActor::Evict()` | QuotaManagerActor | LIFO 驱逐 |

## 行为说明

### 配额检查流程

1. 实例调度请求到达 `InstanceCtrlActor::Schedule()`
2. 检查是否存在配额配置
3. 若无配置或使用量未超限，允许调度
4. 若超限，返回 `TenantQuotaExceeded` 错误并进入冷却期

### 冷却机制

- 配额超限后，租户进入冷却期
- 冷却期内该租户的新调度请求会被拒绝
- 冷却时间可通过 `cooldown_ms` 配置

### LIFO 驱逐策略

当租户配额超限时，优先驱逐最新创建的实例：

1. 获取该租户所有运行实例
2. 按创建时间排序（最新优先）
3. 逐个驱逐直到使用量低于配额

## 配置示例

```yaml
quota:
  config_file: /etc/yuanrong/quota.json
  default_quota:
    max_instances: 50
    max_cpu: 500
    max_memory_mb: 51200
```
