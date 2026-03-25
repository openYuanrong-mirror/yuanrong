# Oneshot 函数

## 概述

Oneshot 是 FaaS 函数的调度策略，为每个请求创建专用实例，执行完成后自动销毁。

## 配置方式

通过函数元数据中的 `instanceMetadata.scalePolicy` 设置：

```json
{
  "name": "my-func",
  "kind": "faas",
  "instanceMetadata": {
    "scalePolicy": "oneshot"
  }
}
```

## 行为特性

| 特性 | 说明 |
|------|------|
| 实例池 | 无，每次请求创建新实例 |
| 实例复用 | 否 |
| 清理机制 | 请求完成后 (timeout + 30s grace period) 自动销毁 |
| 隔离级别 | 严格隔离，每个请求独立实例 |
| 状态恢复 | 不支持 |

## 与普通 FaaS 函数区别

| 特性 | Oneshot | 普通 FaaS |
|------|---------|----------|
| 实例池 | 无 | 有 |
| 实例复用 | 否 | 是 |
| 冷启动开销 | 每次请求 | 仅首次 |
| 适用场景 | 严格隔离、单次任务 | 持续服务 |

## 使用限制

- 仅适用于 `kind: "faas"` 函数
- 不支持 yrlib 运行时函数
- 不支持实例状态恢复
