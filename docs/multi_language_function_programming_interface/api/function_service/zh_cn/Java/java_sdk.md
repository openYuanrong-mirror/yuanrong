# Java SDK

## public interface Context

包名：`org.yuanrong.services.runtime`。

为用户提供函数运行时能力。

```java

public class demo {
    public string handleRequest(JsonObject jsonObject, Context context) {
        RuntimeLogger logger = context.getLogger();
        logger.Log("test");
        return "";
    }
}
```

### Interface description

#### String getRequestID()

获取单个请求的追踪 ID。

- 返回：
  
    requestID (String)：可用于唯一标识一个请求，通常用于日志中追踪单个请求的链路。

#### String getUserData(String key)

获取环境变量和加密环境变量的方法。

- 参数：

   - **key** (Sring) - 环境变量的键。
  
- 返回：
   
    value (Sring)：环境变量值或加密环境变量值。

#### String getFunctionName()

获取函数名称。

- 返回：
  
    functionName (Sring)：函数自身的名称。

#### int getMemorySize()

获取分配给运行中函数的内存大小。

- 返回：
  
    memorySize (int)：函数内存大小。单位：MB。

#### int getCPUNumber()

获取运行中函数分配的 CPU 大小。

- 返回：
 
    cpuNumber (int)：函数 CPU 数量。单位：m，1C=1000m。

#### String getInstanceLabel()

获取实例标签。

- 返回：

    instanceLabel (String): 实例标签。

#### RuntimeLogger getLogger()

获取供用户在标准输出中打印日志的记录器，Logger 接口必须在 SDK 中提供。

- 返回：
  
    logger (RuntimeLogger): 运行时记录器，用于打印日志。

```java

public class demo {
    public string handleRequest(JsonObject jsonObject, Context context) {
        RuntimeLogger logger = context.getLogger();
        logger.log("test log"):
        return"";
    }
}
```

# Function

包名：`org.yuanrong.function`。

## public class Function

函数类用于通过函数名称实现函数间的相互调用。

### Interface description

#### public Function(Context context, String functionNameWithVersion)

使用用户信息（通过 context）以及目标调用函数的名称和版本来初始化 Function 对象。

- 参数：

   - **context** (Context) - 初始化用户的租户、服务等信息到 Function 对象中，通常设置为用户函数的输入参数；如果未指定，将使用当前函数的默认信息。
  
   - **functionNameWithVersion** (String) - 指定的目标调用函数及其版本，如果 invoke 时不带此参数将抛出错误。

#### public Function(String functionNameWithVersion)

使用 `functionNameWithVersion` 初始化 Function 对象，context 将被设置为 null。

#### public Function(Context context)

使用 context 初始化 Function 对象，`functionNameWithVersion` 将被设置为 null。

```java

public class demo {
    public string handleRequest(JsonObject jsonObject, Context context) {
        String funcName = jsonObject.get("func_name").getAsString();
        Function func = new Function(context, funcName);
        return "";
    }
}
```

#### public Function options(CreateOptions opts)

配置目标函数实例，包括 CPU 和内存；如果与目标函数当前配置不相等，将启动一个新实例。

- 参数：

   - opts
  
     - **cpu** (int) - 目标函数实例 CPU。单位：1m，1C=1000m。
    
     - **memory** (int) - 目标函数实例内存。单位：MB。

#### public <T> ObjectRef<T> invoke(String payload)

调用其他函数的方法，这是一个异步方法。

- 参数：
  
   - **payload** (String) - 调用主体，应为 json 类型。
  
- 返回：
  
    ObjectRef (ObjectRef<T>)：调用其他函数的结果。
  
- 抛出：
  
   - **InvokeException** (InvokeException) - OpenYuanrong 普通异常，具体含义参见 InvokeException 类。

```java
  
public class demo {
    public string handleRequest(JsonObject jsonObject, Context context) {
        String funcName = jsonObject.get("func_name").getAsString();
        Function func = new Function(context, funcName);
        ObjectRef<String> obj = func.invoke("{}")
        return obj.get(String.class);
    }
}
```

# InvokeException

包名：`org.yuanrong.function.runtime.exception`。

## public class InvokeException extends RuntimeException

Yuanrong SDK 调用返回的错误类型。

### Interface description

#### public int getErrorCode()

获取错误代码。

- 返回：

    errorCode (int)：调用错误代码。

#### public String getMessage()

获取错误消息。

- 返回：

    message (String)：错误消息。

#### public String toString()

将错误代码和消息组装成固定格式。

- 返回：
   
    errorMsg (String)：`{\"code\":\"errorCode\", \"message\":\"message\"}`。

## Public class CreateOptions

包名：`org.yuanrong.function`。

用于调用。

- 参数：
  
   - **cpu** (int) - 调用目标实例的 CPU。单位：m，1C=1000m。
  
   - **memory** (int) - 调用目标实例的内存。单位：MB。
  
   - **aliasParams** (Map<String, String>) - 目标函数别名。

### Interface description

#### public CreateOptions(int cpu, int memory, Map<String, String> aliasParams)

初始化创建选项对象。

- 参数：
  
   - **cpu** (int) - 调用目标实例的 CPU。单位：m，1C=1000m。
  
   - **memory** (int) - 调用目标实例的内存。单位：MB。
  
   - **aliasParams** (Map<String, String>) - 目标函数别名。

#### public CreateOptions(int cpu, int memory)

初始化时不包含 `aliasParams`。

#### public CreateOptions(Map<String, String> aliasParams)

初始化，CPU 设为 0，内存设为 0。

#### public CreateOptions(int memory)

初始化，CPU 设为 0，并且 `aliasParams` 为空。
  
# ObjectRef<T>

包名：`org.yuanrong.function`。

## public class ObjectRef<T>

用于接收调用返回结果的对象。

### Interface description

#### public T get(int timeoutSec)

获取 `function.invoke()` 的结果并设置超时限制。该方法会将结果赋值给 ObjectRef 对象并返回结果；如果接收返回结果所花费的时间超过 timeoutSec 限制，将抛出错误。

- 参数：
  
   - **timeoutSec** (int) - 接收结果的超时时间限制。
  
- 返回：
  
    T (T)：转换成 T-shape 结果。
  
- 抛出：
  
   - **InvokeException** (InvokeException) - OpenYuanrong 普通异常，具体含义参见 InvokeException 类。

#### public T get()

调用 `get(int timeoutSec)` 方法且不设置超时时间。

#### public T get(Class<?> classType, int timeoutSec)

除了接收和存储结果外，该方法还会检查结果是否符合 classType 格式，并将结果转换为 classType 类型。

- 参数：

   - **timeoutSec** (int) - 接收结果的超时时间限制。

   - **classType** (Class<?>) - 应该等于 T 类型。

- 返回：
 
    T：转换成 T-shape 结果。

- 抛出：

   - **InvokeException** (InvokeException) - OpenYuanrong 普通异常，具体含义参见 InvokeException 类。

#### public T get(Class<?> classType)

调用 `get(Class<?> classType, int timeoutSec)get(int timeoutSec)` 方法且不设置超时时间。
