# InvokeDirect 验证报告

> 日期: 2026-04-16
> 分支: feat/bypass-datasystem-invoke

## 一、功能验证

### 1. SDK invoke_direct 基础功能 (in-cluster)

| Case | 描述 | 结果 |
|------|------|------|
| stateless_invoke_direct | `@yr.invoke` 函数 `.invoke_direct()` 返回 `ObjectRefDirect`，值正确 | PASS |
| instance_invoke_direct | `@yr.instance` 类方法 `.invoke_direct()` 返回 `ObjectRefDirect`，值正确 | PASS |
| invoke_vs_invoke_direct | `.invoke()` 返回 `ObjectRef`，`.invoke_direct()` 返回 `ObjectRefDirect`，结果一致 | PASS |
| invoke_direct_large_data | 1000 元素 list，invoke_direct 正常返回 | PASS |
| invoke_direct_multiple_calls | 连续 10 次 invoke_direct，全部正确 | PASS |

### 2. out-of-cluster 模式 (通过 Frontend)

| Case | 修复前 | 修复后 |
|------|--------|--------|
| 100KB invoke_direct | PASS | PASS |
| 200KB invoke_direct | **卡死** (timeout) | PASS |
| 500KB invoke_direct | 卡死 | PASS |
| 1MB invoke_direct | 卡死 | PASS |
| 4MB invoke_direct | 卡死 | PASS |

### 3. 超阈值行为 (100MB)

| Case | 结果 |
|------|------|
| 99MB invoke_direct | PASS，正常返回 |
| 101MB invoke_direct | RuntimeError: `bypass_datasystem: return value size (xxx bytes) exceeds the 104857600 bytes limit. Use invoke() instead of invoke_direct() for large return values.` |
| 60MB 普通 invoke (DS) | PASS，不受阈值限制 |

## 二、修复的 Bug

### Bug 1: bypass_datasystem 标志在 FunctionProxy 路径丢失

**根因:** `functionsystem/.../invocation_handler.cpp` 的 `InvokeRequestToCallRequest()` 没有将 `InvokeOptions.bypass_datasystem` 复制到 `CallRequest.bypass_datasystem`。

**影响:**

- 通过 FunctionProxy 的 invoke（非 direct connection），bypass_datasystem 始终为 false
- Worker 端不走 bypass 路径，返回值走 DS，但 caller 端以为是 bypass 模式（不做 ref counting）
- 结果：out-of-cluster 模式下 >100KB 数据卡死；in-cluster 模式下无 bypass 性能收益

**修复:**

```cpp
// functionsystem/.../invocation_handler.cpp:45
callRequest->set_bypass_datasystem(request->invokeoptions().bypass_datasystem());
```

### Bug 2: 超阈值截断产生不可反序列化的数据

**根因:** 超过阈值时，C++ 层截断 pickle 序列化后的 raw bytes 前 N 字节返回，破坏序列化格式。

**影响:** Python 反序列化时 `split_buffer` 断言失败，抛出无意义的 `AssertionError`。

**修复:** 超阈值时直接设 `ERR_PARAM_INVALID` 错误码返回，Python 层收到明确的 `RuntimeError`。

```cpp
// src/libruntime/invokeadaptor/invoke_adaptor.cpp:657-665
if (req.bypass_datasystem() && bufSize > BYPASS_DS_TRUNCATION_THRESHOLD) {
    auto msg = fmt::format(
        "bypass_datasystem: return value size ({} bytes) exceeds the {} bytes limit. "
        "Use invoke() instead of invoke_direct() for large return values.",
        bufSize, BYPASS_DS_TRUNCATION_THRESHOLD);
    callResult.set_code(common::ERR_PARAM_INVALID);
    callResult.set_message(msg);
    return callResult;
}
```

## 三、性能对比

测试环境: 单节点 in-cluster，每个数据量 3 轮取平均。

| size | invoke_direct (ms) | invoke/DS (ms) | 延迟比 | direct RSS (MB) | DS RSS (MB) | RSS 节省 |
|------|--------------------|----------------|--------|-----------------|-------------|----------|
| 1MB | 8.6 | 6.2 | 1.4x | 127 | 130 | 2% |
| 5MB | 40 | 20 | 2.0x | 163 | 178 | 8% |
| 10MB | 68 | 37 | 1.8x | 231 | 259 | 11% |
| 20MB | 144 | 63 | 2.3x | 383 | 442 | 13% |
| 40MB | 375 | 155 | 2.4x | 595 | 714 | 17% |
| 60MB | 620 | 226 | 2.7x | 816 | 901 | 9% |
| 80MB | 816 | 304 | 2.7x | 1018 | 1258 | 19% |

### 结论

- **延迟:** invoke_direct 在大数据量（>5MB）下比 DS 路径慢 2-3x。原因是 gRPC inline 传输整个序列化消息（protobuf 编解码开销），而 DS 路径通过共享内存零拷贝传输。
- **内存:** invoke_direct 的 RSS 峰值比 DS 路径低 ~10-20%，因为跳过了 DS 的 buffer 管理和引用计数结构。
- **适用场景:** invoke_direct 适合小数据量（<5MB）+ 无需 DS 引用计数管理的场景（如一次性调用、无后续 ObjectRef 传递）。大数据量场景应使用普通 invoke。

## 四、配置参数

| 参数 | 值 | 文件 |
|------|-----|------|
| BYPASS_DS_TRUNCATION_THRESHOLD | 100MB | src/libruntime/utils/constants.h |
| YR_MAX_GRPC_SIZE | 128MB | src/dto/config.h |

## 五、测试用例

测试代码位于 `test/smoke/invoke-direct/`：

| 文件 | 描述 |
|------|------|
| run_test.sh | 安装 whl、启动 yr、运行测试、清理 |
| test_invoke_direct.py | SDK (cluster-internal) + Frontend HTTP (cluster-external) 测试 |
| services.yaml | yrlib service 定义 |

运行方式（需在 dev container 中）:

```bash
cd test/smoke/invoke-direct && bash run_test.sh
```
