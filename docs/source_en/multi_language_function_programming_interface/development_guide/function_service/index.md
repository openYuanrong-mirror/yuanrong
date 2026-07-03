# Function Services

```{eval-rst}
.. toctree::
   :glob:
   :hidden:

   function-configuration
   version-management
   response-stream
```

openYuanrong provides function service capabilities, supporting openYuanrong functions to run as Serverless services, accessible via HTTP requests. Service instances automatically scale elastically based on request concurrency, scaling down to 0 when there are no requests. Function services define Handler methods as request processing entry points, with the following signatures.

:::::{tab-set}
::::{tab-item} Python

- handler: Method name, customizable.
- event: Request parameters for the function service, including request headers, request body, etc., in JSON object format.
- context: Context information provided by the openYuanrong runtime. For interface introduction, see Function Service [Python SDK](../../api/function_service/Python/python_sdk.rst).

```python
def handler(event, context)
```

::::

::::{tab-item} C++

- handler: Method name, customizable.
- event: Request parameters for the function service, including request headers, request body, etc., in string format.
- context: Context information provided by the openYuanrong runtime. For interface introduction, see Function Service [C++ SDK](../../api/function_service/Cpp/cpp_sdk.md).

```cpp
std::string HandleRequest(const std::string &event, Function::Context &context) 
```

::::

::::{tab-item} Java

- handler: Method name, customizable.
- event: Request parameters for the function service, including request headers, request body, etc., in JSON object format.
- context: Context information provided by the openYuanrong runtime. For interface introduction, see Function Service [Java SDK](../../api/function_service/Java/java_sdk.md) .

```java
public String handler(JsonObject event, Context context)
```

::::
:::::

The Handler method returns a string. Below is a complete method example:

:::::{tab-set}
::::{tab-item} Python

```python
import datetime

# Service execution entry, executed on every request
def handler(event, context):
   print("received request,event content:", event)

   response = ""
   try:
      name = event.get("name")
      # Get configured environment variables, set when registering and updating functions
      show_date = context.getUserData("show_date")
      if show_date is not None:
            response = "hello " + name + ",today is " + datetime.date.today().strftime('%Y-%m-%d')
      else:
            response = "hello " + name
   except Exception as e:
      print(e)
      response = "please enter your name,for example:{'name':'yuanrong'}"

   return response
```

::::
::::{tab-item} C++

```cpp
#include <string>
#include <ctime>
#include <nlohmann/json.hpp>

#include "Runtime.h"
#include "Function.h"
#include "yr/yr.h"

std::string HandleRequest(const std::string &event, Function::Context &context) {
    std::cout << "received request,event content:" << event << std::endl;
    std::string response = "";
    try {
        nlohmann::json jsonData = nlohmann::json::parse(event);
        // Read JSON data and output
        std::string name = jsonData["name"];
        response += "hello ";
        response += name;
            
        std::string showDate = context.GetUserData("show_date");
        if (showDate != "") {
            time_t now = time(0);
            tm *ltm = localtime(&now);
                
            std::stringstream timeStr;
            timeStr << ltm->tm_year + 1900 << "-";
                timeStr << ltm->tm_mon + 1 << "-";
                timeStr << ltm->tm_mday;
            response += ",today is ";
            response += timeStr.str();
        }
    } catch (const std::exception& e) {
        std::cout << "JSON parsing error:" << e.what() << std::endl;
        response = "please enter your name,for example:{'name':'yuanrong'}";
    }
    return response;
}

int main(int argc, char *argv[])
{
    Function::Runtime rt;
    // Also need to register this method in the main() function
    rt.RegisterHandler(HandleRequest);
    rt.Start(argc, argv);
    return 0;
}
```

::::

::::{tab-item} Java

```java

import org.yuanrong.services.runtime.Context;
import com.google.gson.JsonObject;
import java.time.LocalDate;

public String handler(JsonObject event, Context context) {
    System.out.println("received request,event content:" + event);
    String response = "";
    try {
    String name = event.get("name").getAsString();
    // Get configured environment variables, set when registering and updating functions
    String showDate = context.getUserData("show_date");
        if (showDate != null) {
            response = "hello " + name + ",today is " + LocalDate.now();
        } else {
            response = "hello " + name;
        }
    } catch(Exception e) {
        e.printStackTrace();
        response = "please enter your name,for example:{'name':'yuanrong'}";
    }
    return response;       
}
```

::::
:::::

View [Deploy openYuanrong Service Applications](../../../deploy/service_app_guide.md) to learn how to deploy function services.

## Function Lifecycle Callbacks

When function instance lifecycle events occur, corresponding callback methods can be triggered, including Initializer and PreStop. Callback methods can be implemented or not based on actual business needs.

### Initializer Callback

The Initializer callback method executes after the function instance starts and before the request processing method (Handler). During the function instance lifecycle, it successfully executes once and only once. If the initialization method fails, requests sent to that function instance will directly return failure, and the instance will be automatically reclaimed by the system.

The initializer method can be used to handle backend connection establishment logic. In scenarios where a single function instance is configured to handle multiple concurrent requests, connections can be reused between requests, avoiding repeated connection establishment and reducing processing latency.

The Initializer callback method signature is as follows:

:::::{tab-set}
::::{tab-item} Python

- initializer: Method name, customizable.
- context: Context information provided by the openYuanrong runtime. For interface introduction, see Function Service [Python SDK](../../api/function_service/Python/python_sdk.rst).

```python
def initializer(context)
```

::::
::::{tab-item} C++

- Initializer: Method name, customizable.
- context: Context information provided by the openYuanrong runtime. For interface introduction, see Function Service [C++ SDK](../../api/function_service/Cpp/cpp_sdk.md).

```cpp
void Initializer(Function::Context &context)
```

::::
::::{tab-item} Java

- initializer: Method name, customizable.
- context: Context information provided by the openYuanrong runtime. For interface introduction, see Function Service [Java SDK](../../api/function_service/Java/java_sdk.md).

```java
public void initializer(Context context) 
```

::::
:::::

The Initializer method has no return value. A simple example is as follows:

:::::{tab-set}
::::{tab-item} Python

```python
def initializer(context):
   print("function instance initialization completed")
```

::::
::::{tab-item} C++

```cpp
std::string HandleRequest(const std::string &event, Function::Context &context) {
    return "ok";
}

void Initializer(Function::Context &context) {
    std::cout << "function instance initialization completed" << std::endl;
    return;
}

int main(int argc, char *argv[])
{
    Function::Runtime rt;
    rt.RegisterHandler(HandleRequest);
    // Also need to register this method in the main() function
    rt.RegisterInitializerFunction(Initializer);
    rt.Start(argc, argv);
    return 0;
}

```

::::
::::{tab-item} Java

```java
public void initializer(Context context) {
    System.out.println("function instance initialization completed");
}
```

::::
:::::

### PreStop Callback

The PreStop callback method executes before the function instance exits, and can be used for operations such as disconnecting links and saving persistent data.

The PreStop callback method signature is as follows:

:::::{tab-set}
::::{tab-item} Python

- pre_stop: Method name, customizable.

```python
def pre_stop()
```

::::
::::{tab-item} C++

- PreStop: Method name, customizable.

```cpp
void PreStop(Function::Context &context) 
```

::::
::::{tab-item} Java

- preStop: Method name, customizable.

```java
public void preStop(Context context)
```

::::
:::::

The PreStop method has no return value. A simple example is as follows:

:::::{tab-set}
::::{tab-item} Python

```python
def pre_stop():
   print("function instance is being destroyed")
```

::::
::::{tab-item} C++

```cpp
std::string HandleRequest(const std::string &event, Function::Context &context) {
    return "ok";
}

void PreStop(Function::Context &context) {
    std::cout << "function instance is being destroyed" << std::endl;
}

int main(int argc, char *argv[])
{
    Function::Runtime rt;
    rt.RegisterHandler(HandleRequest);
    // Also need to register this method in the main() function
    rt.RegisterPreStopFunction(PreStop);
    rt.Start(argc, argv);
    return 0;
}
```

::::
::::{tab-item} Java

```java
public void preStop(Context context) {
    System.out.println("function instance is being destroyed");
}
```

::::
:::::

## Function Logs

Logs printed by function methods to standard output stdout are collected and stored by openYuanrong. You can use the following methods to print logs.

### Using openYuanRong's Logger

You can print logs through the context method `getLogger()`, obtaining the same output format as openYuanrong components. Each log contains information such as time, request ID, and log level. A simple example is as follows.

:::::{tab-set}
::::{tab-item} Python

```python
def handler(event, context):
    context.getLogger().info("hello world")
    return 'ok'
```

::::
::::{tab-item} C++

```cpp
std::string HandlerRequest(const std::string &event, Function::Context &context) {
    Function::FunctionLogger logger = context.GetLogger();
    logger.setLevel("INFO");
    logger.Info("hello world");
    return "ok";
}

int main(int argc, char *argv[])
{
    Function::Runtime rt;
    // Also need to register this method in the main() function
    rt.RegisterHandler(HandleRequest);
    rt.Start(argc, argv);
    return 0;
}
```

::::
::::{tab-item} Java

```java
public String handler(JsonObject event, Context context) {
    context.getLogger().info("hello world");
    return "ok";
}
```

::::
:::::

Running the function, the expected output log content is as follows.

```bash
2025-xx-xx xx:xx:xx xxxxxxxx-xxxx-xxxx-xxxx-xxxxx****xx [INFO] hello world
```

### Using Programming Language Log Output Functions

Logs printed using programming language log output functions will be output as-is to log files. A simple example is as follows.

:::::{tab-set}
::::{tab-item} Python

```python
def handler(event, context):
    print('hello world')
    return 'ok'
```

::::
::::{tab-item} C++

```cpp
std::string HandlerRequest() {
    std::cout << "hello world" << std::endl;
    return "ok";
}

int main(int argc, char *argv[])
{
    Function::Runtime rt;
    // Also need to register this method in the main() function
    rt.RegisterHandler(HandleRequest);
    rt.Start(argc, argv);
    return 0;
}
```

::::
::::{tab-item} Java

```java
public String handler() {
    System.out.println("hello world");
    return "ok";
}
```

::::
:::::

Running the service, the expected output log content is as follows.

```bash
hello world
```

## Instance Elasticity Policy

openYuanrong supports elasticity policies based on concurrency. When concurrency reaches the configured single instance concurrency, function instance scaling is triggered. When a function instance has no request processing for 1 minute, scaling in is triggered, and function instances can scale down to 0.

## Instance Scheduling

openYuanrong will select appropriate nodes to run functions based on the resources specified by the function and the configured scheduling policies. For details, refer to the [Scheduling](../scheduling/index.md) section.

## Request Scheduling

openYuanrong supports configuring different request scheduling policies for functions, including concurrency, round-robin, and microservice.

- concurrency: The scheduling strategy is based on the current instance concurrency situation. Requests will be prioritized to instances with lower concurrency.
- round-robin: The scheduling strategy is round-robin scheduling. Requests will be轮流 allocated to different instances.
- microservice: The scheduling strategy indicates that you have not specified a scheduling strategy for a single function. The specific scheduling strategy used will be specified when the openYuanrong cluster is deployed.

## More Usage Methods

- [Configuring Functions](./function-configuration.md)
- [Version Management](./version-management.md)
- [Stream Response](./response-stream.md)
