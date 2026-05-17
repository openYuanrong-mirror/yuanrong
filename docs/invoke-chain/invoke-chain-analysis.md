# Invoke 全链路调研 + Bypass DataSystem 分析

> 日期: 2026-04-15
> 分支: feat/bypass-datasystem-invoke

## 一、完整 Invoke 链路（SDK Use 场景）

### 组件链路

```text
pythonsdk(caller) -> libruntime(caller) -> [HTTP] -> frontend -> gosdk(frontend) -> libruntime(frontend)
   -> [gRPC] -> functionproxy -> [gRPC] -> libruntime(worker) -> pythonsdk(worker)
```

### 详细调用链

```text
─── Caller 节点 ─────────────────────────────────────────────────

[1] sandbox.invoke
      api/python/yr/sandbox/sandbox.py

[2] InstanceProxy.invoke / MethodProxy._invoke
      api/python/yr/decorator/instance_proxy.py:865-962
      - signature.package_args() 打包参数
      - 构建 FunctionMeta protobuf
      - runtime.invoke_instance(func_meta, instance_id, args, opts, return_nums)

[3] cluster_mode_runtime.invoke_instance
      api/python/yr/cluster_mode_runtime.py:273
      - _package_python_args(): ObjectRef -> InvokeArg(is_ref=True), 值 -> serialize + InvokeArg(is_ref=False)

[4] fnruntime.pyx: invoke_instance
      api/python/yr/fnruntime.pyx:1843-1885
      - parse_invoke_args() -> build_invoke_arg(): Python -> CInvokeArg
      - parse_invoke_opts(): 设置 bypassDatasystem 等
      - c_libruntime.InvokeByInstanceId(functionMeta, instanceID, invokeArgs, opts, returnObjs)

[5] C++ Libruntime::InvokeByInstanceId
      src/libruntime/libruntime.cpp:437-531
      - GenerateReturnObjectIds()
      - PreProcessArgs(): 大参数 Put 到 DS, IncreaseObjRef             [DS 交互]
      - memStore->AddReturnObject()
      - memStore->IncreDSGlobalReference(returnObjIds) (out-of-cluster) [DS 交互]
      - dependencyResolver->ResolveDependencies()
      - callback:
          PutRefArgToDs(): AlsoPutToDS(引用参数+嵌套对象)               [DS 交互]
          spec->BuildInstanceInvokeRequest()
            invoke_spec.cpp:330-358
            - 构建 InvokeRequest protobuf
            - invokeOptions->set_bypass_datasystem(opts.bypassDatasystem)
          invokeAdaptor->InvokeInstanceFunction()
            -> FSClient::InvokeAsync() -> gRPC stream 发出

─── 网络: Caller -> Frontend (HTTP) ─────────────────────────────

[6] Frontend HTTP /frontend/v1/instance/invoke
      frontend/pkg/frontend/api/functionsystem/handler.go:154-213
      - InvokeHandler: body = ReadAll(body)
      - util.NewClient().InvokeInstanceRaw(body, option)

[7] InvokeInstanceRaw
      frontend/pkg/frontend/common/util/client.go:407-409
      - clientLibruntime.InvokeByInstanceIdRaw(invokeReq, option)

─── Frontend 节点 ───────────────────────────────────────────────

[8] Go SDK: InvokeByInstanceIdRaw (yuanrong Go libruntime)
      -> 解析 raw bytes 为 InvokeRequest -> 调用底层 C++ Libruntime

[9] C++ Libruntime::InvokeByInstanceId (Frontend 节点的 C++ libruntime)
      与 [5] 相同的代码路径
      - PreProcessArgs()                                                [DS 交互]
      - memStore->IncreDSGlobalReference(returnObjIds)                  [DS 交互]
      - PutRefArgToDs()                                                 [DS 交互]
      - BuildInstanceInvokeRequest()
      - invokeAdaptor->InvokeInstanceFunction() -> gRPC 发出

─── 网络: Frontend -> FunctionProxy (gRPC) ──────────────────────

[10] gRPC 传输层
       src/libruntime/fsclient/grpc/fs_intf_grpc_reader_writer.cpp
       Direct Connection:
         TransDirectInvokeRequest() (line 251-268)
         InvokeRequest -> CallRequest 转换
         callreq->set_bypass_datasystem(invokereq->invokeoptions().bypass_datasystem())
       Via FunctionProxy:
         InvokeRequest 原样发送给 functionsystem

─── FunctionProxy (Functionsystem) ─────────────────────────────

[11] Functionsystem 接收 InvokeRequest
       functionsystem 仓
       - 路由到目标 worker 节点
       - InvokeRequest -> CallRequest 转换（若未在 [10] 中转换）

─── 网络: FunctionProxy -> Worker (gRPC) ───────────────────────

─── Worker 节点 ─────────────────────────────────────────────────

[12] InvokeAdaptor::Call
       src/libruntime/invokeadaptor/invoke_adaptor.cpp:569-703

       参数解析 -- ParseRequest (line 540-567):
         OBJECT_REF: memStore->GetBuffer(argId) -- 从 DS/memStore 获取   [DS 交互]
         VALUE: 直接从 protobuf 读取

       Return Object 初始化 (line 628-632):
         if (apiType != Function || req.bypass_datasystem())
           -> returnObjects 全部设 alwaysNative = true

[13] AllocReturnObject (被 functionExecuteCallback 调用)
       src/libruntime/libruntime.cpp:964-1003
       if (alwaysNative || (小对象 && 无嵌套)):
         -> NativeBuffer (不经 DS)
       else:
         -> memStore->IncreGlobalReference + CreateBuffer in DS          [DS 交互]

[14] functionExecuteCallback
       根据语言类型调用 Python/Go/Java/C++ handler
       handler 将返回值写入 returnObjects 的 buffer

[15] Call 返回值处理 (line 652-676)
       for each returnObject:
         if (native && !putDone):
           -> 内联到 CallResult.smallObjects (bypass 时若 >5MB 截断)
         else if (!bypass):
           -> 加入 objectsInDs (caller 从 DS 自取)

       -> 返回 CallResult

─── 返回路径: Worker -> FunctionProxy -> Frontend ──────────────

[16] CallResult 通过 gRPC stream 返回
       经 FunctionProxy 转发回 Frontend

[17] Frontend 节点: InvokeNotifyHandler
       src/libruntime/invokeadaptor/invoke_adaptor.cpp:1437-1490
       成功路径:
         HandleReturnedObject(req, spec)                                [DS 交互]
           smallObjects -> memStore->Put
           非 smallObject 的 returnId -> dsObjs
           inCluster: memStore->IncreDSGlobalReference(dsObjs)
           memStore->SetReady(returnIds)

         memStore->UnbindObjRefInReq(rawRequestId)
         memStore->DecreGlobalReference(ids) -- 释放参数引用             [DS 交互]

[18] Frontend getRes
       frontend/pkg/frontend/common/util/client.go:221-273
       GetAsync(objID, callback):
         -> memStore->SetReady 后触发 callback
         -> 正常模式: GDecreaseRef(objID)                               [DS 交互]
         -> bypass 模式: 跳过 GDecreaseRef

       -> 返回 HTTP response body

─── 返回路径: Frontend -> Caller ───────────────────────────────

[19] Caller 节点: InvokeNotifyHandler (同 [17])
       HandleReturnedObject
       DecreGlobalReference(参数引用)                                   [DS 交互]

[20] Python SDK 接收返回值
       fnruntime.pyx: 提取 returnObjs 中的 object ID
       -> MethodProxy._invoke 返回 ObjectRef(id, need_incre=False)
       -> bypass 模式: ObjectRefDirect(id, need_incre=False, need_decre=False)

       ObjectRef.__del__:
         正常: DecreaseRef                                              [DS 交互]
         bypass: 跳过
```

### DS 交互汇总

| # | 位置 | 节点 | DS 操作 | bypass 返回值路径是否跳过 |
|---|------|------|---------|-------------------------|
| A | PreProcessArgs | Caller + Frontend | Put(大参数), IncreaseObjRef | 否（参数侧） |
| B | Return Object 注册 | Caller + Frontend | IncreDSGlobalReference (out-of-cluster) | **否** |
| C | PutRefArgToDs | Caller + Frontend | AlsoPutToDS | 否（参数侧） |
| D | ParseRequest | Worker | GetBuffer (OBJECT_REF 参数) | 否（参数侧） |
| E | AllocReturnObject | Worker | IncreGlobalRef + CreateBuffer | **是** (alwaysNative) |
| F | Call 返回值 | Worker | objectsInDs | **是** (内联 smallObjects) |
| G | HandleReturnedObject | Caller + Frontend | IncreDSGlobalRef (dsObjs) | 间接跳过 (dsObjs 为空) |
| H | getRes | Frontend | GDecreaseRef | **是** |
| I | NotifyHandler 清理 | Caller + Frontend | DecreGlobalReference (参数引用) | 否（参数侧，正常行为） |
| J | ObjectRef GC | Caller Python | DecreaseRef | **是** (ObjectRefDirect) |

---

## 二、Bypass DataSystem 当前实现分析

### 实现概述

bypass_datasystem 的设计目标：函数返回值跳过 datasystem，直接通过 gRPC message 内联传递（smallObjects），避免 DS 的 Put/Get/引用计数 开销。

### bypass 标志透传链路

```text
Python InvokeOptions.bypass_datasystem (config.py)
  -> fnruntime.pyx: opts.bypassDatasystem = opt.bypass_datasystem
    -> C++ InvokeOptions.bypassDatasystem (invoke_options.h)
      -> InvokeSpec::BuildInstanceInvokeRequest:
          invokeOptions->set_bypass_datasystem() (core_service.proto)
        -> TransDirectInvokeRequest (或经 FunctionProxy):
            callreq->set_bypass_datasystem() (runtime_service.proto)
          -> Worker Call(): req.bypass_datasystem()

Frontend HTTP:
  X-Bypass-Datasystem header -> convert() -> InvokeRequest.BypassDataSystem
    -> convertCommonInvokeOption() -> Go InvokeOptions.BypassDataSystem
      -> C++ InvokeOptions.bypassDatasystem (同上路径)
```

透传完整性：全链路已覆盖。
