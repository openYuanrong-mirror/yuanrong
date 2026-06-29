# Simple Function Programming Examples

This section introduces how to develop applications using stateful and stateless functions through examples. You can use these examples as base projects to quickly get started.

:::{note}
Running examples requires first [installing openYuanrong](../../deploy/installation.md) SDK, command-line tool yr, and having deployed openYuanrong [on hosts](../../deploy/deploy_processes/index.md).
:::

(example-project-stateless-function)=

## Stateless Function Example Project

:::::{tab-set}

::::{tab-item} Python

1. Prepare the example project

    Create a new working directory `python-stateless-function` with the following file structure. Here, example.py is the application code.

    ```bash
    python-stateless-function
    └── example.py
    ```

    :::{dropdown} example.py file content
    :chevron: down-up
    :icon: chevron-down

    ```python
    import yr
    
    # Define stateless function
    @yr.invoke
    def say_hello(name):
        return 'hello, ' + name


    # Init only once
    yr.init()
    
    # Asynchronously invoke stateless functions in parallel
    results_ref = [say_hello.invoke('yuanrong') for i in range(3)]
    print(yr.get(results_ref))
    
    # Release environmental resources
    yr.finalize()
    ```
    
    :::

2. Run the program

    Run the program in the `python-stateless-function` directory, output as follows:

    ```bash
    python example.py
    # ['hello, yuanrong', 'hello, yuanrong', 'hello, yuanrong']
    ```

::::

::::{tab-item} C++

:::{note}
Example execution depends on make, g++, and cmake.
:::

1. Prepare the example project

    Create a new working directory `cpp-stateless-function` with the following file structure. Here, the build directory is used to store files generated during compilation, CMakeLists.txt is the configuration file used by the CMake build system, and example.cpp is the application code.

    ```bash
    cpp-stateless-function
    ├── build
    ├── CMakeLists.txt
    └── src
        └── example.cpp
    ```

    :::{dropdown} example.cpp file content
    :chevron: down-up
    :icon: chevron-down

    ```cpp
    #include <iostream>
    #include "yr/yr.h"
    
    // Define stateless function
    std::string SayHello(std::string name)
    {
        return "hello, " + name;
    }
    YR_INVOKE(SayHello)


    int main(int argc, char *argv[])
    {
        // Init only once
        YR::Init(YR::Config{}, argc, argv);
    
        // Asynchronously invoke stateless functions in parallel
        std::vector<YR::ObjectRef<std::string>> results_ref;
        for (int i = 0; i < 3; i++) {
            auto result_ref = YR::Function(SayHello).Invoke(std::string("yuanrong"));
            results_ref.emplace_back(result_ref);
        }
    
        for (auto result : YR::Get(results_ref)) {
            std::cout << *result << std::endl;
        }
    
        // Release environmental resources
        YR::Finalize();
        return 0;
    }
    ```
    
    :::
    :::{dropdown} CMakeLists.txt file content, **need to modify YR_INSTALL_PATH to your openYuanrong installation path**
    :chevron: down-up
    :icon: chevron-down
    
    ```cmake
    cmake_minimum_required(VERSION 3.16.1)
    # Specify project name, e.g.: cpp-stateless-function
    project(cpp-stateless-function LANGUAGES C CXX)
    set(CMAKE_CXX_STANDARD 17)
    
    # Specify compilation output directory in build directory
    set(SOURCE_DIR ${CMAKE_CURRENT_SOURCE_DIR})
    set(BINARY_DIR ${SOURCE_DIR}/build)
    set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${BINARY_DIR})
    
    set(CMAKE_CXX_FLAGS "-pthread")
    set(BUILD_SHARED_LIBS ON)
    
    # Replace YR_INSTALL_PATH value with actual openYuanrong installation path
    set(YR_INSTALL_PATH "/usr/local/lib/python3.9/site-packages/yr")
    link_directories(${YR_INSTALL_PATH}/cpp/lib)
    include_directories(
        ${YR_INSTALL_PATH}/cpp/include
    )
    
    # Generate executable file example, modify example.cpp to your corresponding source file
    add_executable(example src/example.cpp)
    target_link_libraries(example yr-api)
    
    # Generate dynamic library file example-dll, modify example.cpp to your corresponding source file
    add_library(example-dll SHARED src/example.cpp)
    target_link_libraries(example-dll yr-api)
    ```
    
    :::

2. Build

    In the `cpp-stateless-function/build` directory, execute the following command to build the application:

    ```bash
    cmake ..
    make
    ```

    Successful build will generate driver program `example` and dynamic library `libexample-dll.so` containing stateless function definitions in this directory.

    :::{note}
    Stateless functions may execute on any node in the openYuanrong cluster. Therefore, before running the driver program, you need to copy the `libexample-dll.so` file to the same path on other nodes.
    :::

3. Run the program

    Run the program in the `cpp-stateless-function/build` directory, output as follows:

    ```bash
    ./example --codePath=$(pwd)
    # hello, yuanrong
    # hello, yuanrong
    # hello, yuanrong
    ```

::::
::::{tab-item} Java

:::{note}
Example execution depends on java 8 and maven.
:::

1. Prepare the example project

    Create a new working directory `java-stateless-function` with the following file structure. Here, pom.xml is the maven configuration file, and Greeter.java and Main.java are the application code.

    ```bash
    java-stateless-function
    ├── pom.xml
    └── src
        └── main
            └── java
                └── com
                    └── yuanrong
                        └── example
                            ├── Greeter.java
                            └── Main.java
    ```

    :::{dropdown} pom.xml file content, **please refer to [Install Java SDK](install-yuanrong-java-sdk) and configure dependency yr-api-sdk**
    :chevron: down-up
    :icon: chevron-down

    ```xml
    <?xml version="1.0" encoding="UTF-8"?>

    <project xmlns="http://maven.apache.org/POM/4.0.0"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
        <modelVersion>4.0.0</modelVersion>

        <groupId>org.yuanrong.example</groupId>
        <artifactId>example</artifactId>
        <version>1.0.0</version>

        <properties>
            <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
            <maven.compiler.source>1.8</maven.compiler.source>
            <maven.compiler.target>1.8</maven.compiler.target>
        </properties>

        <dependencies>
            <dependency>
                <!-- Modify version number to your actual version -->
                <groupId>org.yuanrong</groupId>
                <artifactId>yr-api-sdk</artifactId>
                <version>1.0.0</version>
            </dependency>
        </dependencies>

        <build>
            <plugins>
                <plugin>
                    <groupId>org.apache.maven.plugins</groupId>
                    <artifactId>maven-assembly-plugin</artifactId>
                    <executions>
                        <execution>
                            <phase>package</phase>
                            <goals>
                                <goal>single</goal>
                            </goals>
                        </execution>
                    </executions>
                    <configuration>
                        <archive>
                            <manifest>
                                <mainClass>org.yuanrong.example.Main</mainClass>
                            </manifest>
                        </archive>
                        <descriptorRefs>
                            <descriptorRef>jar-with-dependencies</descriptorRef>
                        </descriptorRefs>
                        <appendAssemblyId>false</appendAssemblyId>
                    </configuration>
                </plugin>
            </plugins>
        </build>
    </project>
    ```

    :::
    :::{dropdown} Greeter.java file content
    :chevron: down-up
    :icon: chevron-down

    ```java
    package org.yuanrong.example;

    public class Greeter {
        // Define stateless function
        public static String sayHello(String name) {
            return "hello, " + name;
        }
    }
    ```

    :::
    :::
    :::{dropdown} Main.java file content
    :chevron: down-up
    :icon: chevron-down

    ```java
    package org.yuanrong.example;

    import org.yuanrong.Config;
    import org.yuanrong.api.YR;
    import org.yuanrong.runtime.client.ObjectRef;
    import org.yuanrong.exception.YRException;

    import java.util.HashMap;
    import java.util.ArrayList;
    import java.util.List;

    public class Main {
        public static void main(String[] args) throws YRException {
            // Init only once
            YR.init(new Config());

            // Asynchronously invoke stateless functions in parallel
            List<ObjectRef> resultsRef = new ArrayList<>();
            for (int i = 0; i < 3; i++) {
                ObjectRef resultRef = YR.function(Greeter::sayHello).invoke("yuanrong");
                resultsRef.add(resultRef);
            }

            for (ObjectRef resultRef : resultsRef) {
                System.out.println(YR.get(resultRef, 30));
            }

            // Release environmental resources
            YR.Finalize();
        }
    }
    ```

    :::

2. Build

    In the `java-stateless-function` directory, execute the following command to build the application:

    ```bash
    mvn clean package
    ```

    Successful build will generate jar package `example-1.0.0.jar` in the `java-stateless-function/target` directory.

    :::{note}
    Stateless functions may execute on any node in the openYuanrong cluster. Therefore, before running the program, you need to copy the `example-1.0.0.jar` file to the same path on other nodes.
    :::

3. Run the program

    Run the program in the `java-stateless-function` directory, output as follows:

    ```bash
    java -Dyr.codePath=$(pwd)/target -cp target/example-1.0.0.jar org.yuanrong.example.Main
    # hello, yuanrong
    # hello, yuanrong
    # hello, yuanrong
    ```

::::
:::::

(example-project-stateful-function)=

## Stateful Function Example Project

:::::{tab-set}
::::{tab-item} Python

1. Prepare the example project

    Create a new working directory `python-stateful-function` with the following file structure. Here, example.py is the application code.

    ```bash
    python-stateful-function
    └── example.py
    ```

    :::{dropdown} example.py file content
    :chevron: down-up
    :icon: chevron-down

    ```python
    # example.py
    import yr
    
    # Define stateful function
    @yr.instance
    class Object:
        def __init__(self):
            self.value = 0
    
        def save(self, value):
            self.value = value
    
        def get(self):
            return self.value


    # Init only once
    yr.init()
    
    # Create three stateful function instances
    objs = [Object.invoke() for i in range(3)]
    
    # Asynchronously invoke stateful functions in parallel
    [obj.save.invoke(9) for obj in objs]
    results_ref = [obj.get.invoke() for obj in objs]
    print(yr.get(results_ref))
    
    # Destroy stateful function instance
    [obj.terminate() for obj in objs]
    
    # Release environmental resources
    yr.finalize()
    ```
    
    :::

2. Run the program

    Run the program in the `python-stateful-function` directory, output as follows:

    ```bash
    python example.py
    # [9, 9, 9]
    ```

::::
::::{tab-item} C++

:::{note}
Example execution depends on make, g++, and cmake.
:::

1. Prepare the example project

    Create a new working directory `cpp-stateful-function` with the following file structure. Here, the build directory is used to store files generated during compilation, CMakeLists.txt is the configuration file used by the CMake build system, and example.cpp is the application code.

    ```bash
    cpp-stateful-function
    ├── build
    ├── CMakeLists.txt
    └── src
        └── example.cpp
    ```

    :::{dropdown} example.cpp file content
    :chevron: down-up
    :icon: chevron-down

    ```cpp
    #include <iostream>
    #include "yr/yr.h"

    // Define stateful function
    class Object {
    public:
        Object() {}
        Object(int value) { this->value = value; }

        static Object *FactoryCreate(int value) {
            return new Object(value);
        }

        void Save(int value) {
            this->value = value;
        }

        int Get() {
            return value;
        }

        YR_STATE(value);

    private:
        int value;
    };
    YR_INVOKE(Object::FactoryCreate, &Object::Save, &Object::Get);

    int main(int argc, char *argv[])
    {
        // Init only once
        YR::Init(YR::Config{}, argc, argv);

        // Create three stateful function instances
        std::vector<YR::NamedInstance<Object>> objects;
        for (int i = 0; i < 3; i++) {
            auto obj = YR::Instance(Object::FactoryCreate).Invoke(0);
            objects.emplace_back(obj);
        }

        // Asynchronously invoke stateful functions in parallel
        std::vector<YR::ObjectRef<int>> results_ref;
        for (auto obj : objects) {
            obj.Function(&Object::Save).Invoke(9);
            auto result_ref = obj.Function(&Object::Get).Invoke();
            results_ref.emplace_back(result_ref);
        }

        for (auto result : YR::Get(results_ref)) {
            std::cout << *result << std::endl;
        }

        // Destroy stateful function instance
        for (auto obj : objects) {
            obj.Terminate();
        }

        // Release environmental resources
        YR::Finalize();
        return 0;
    }
    ```

    :::
    :::{dropdown} CMakeLists.txt file content, **need to modify YR_INSTALL_PATH to your openYuanrong installation path**
    :chevron: down-up
    :icon: chevron-down

    ```cmake
    cmake_minimum_required(VERSION 3.16.1)
    # Specify project name, e.g.: cpp-stateful-function
    project(cpp-stateful-function LANGUAGES C CXX)
    set(CMAKE_CXX_STANDARD 17)

    # Specify compilation output directory in build directory
    set(SOURCE_DIR ${CMAKE_CURRENT_SOURCE_DIR})
    set(BINARY_DIR ${SOURCE_DIR}/build)
    set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${BINARY_DIR})

    set(CMAKE_CXX_FLAGS "-pthread")
    set(BUILD_SHARED_LIBS ON)

    # Replace YR_INSTALL_PATH value with actual openYuanrong installation path
    set(YR_INSTALL_PATH "/usr/local/lib/python3.9/site-packages/yr")
    link_directories(${YR_INSTALL_PATH}/cpp/lib)
    include_directories(
        ${YR_INSTALL_PATH}/cpp/include
    )

    # Generate executable file example, modify example.cpp to your corresponding source file
    add_executable(example src/example.cpp)
    target_link_libraries(example yr-api)

    # Generate dynamic library file example-dll, modify example.cpp to your corresponding source file
    add_library(example-dll SHARED src/example.cpp)
    target_link_libraries(example-dll yr-api)
    ```

    :::

2. Build

    In the `cpp-stateful-function/build` directory, execute the following command to build the application:

    ```bash
    cmake ..
    make
    ```

    Successful build will generate driver program `example` and dynamic library `libexample-dll.so` containing stateful function definitions in this directory.

    :::{note}
    Stateful functions may execute on any node in the openYuanrong cluster. Therefore, before running the driver program, you need to copy the `libexample-dll.so` file to the same path on other nodes.
    :::

3. Run the program

    Run the program in the `cpp-stateful-function/build` directory, output as follows:

    ```bash
    ./example --codePath=$(pwd)
    # 9
    # 9
    # 9
    ```

::::
::::{tab-item} Java

:::{note}
Example execution depends on java 8 and maven.
:::

1. Prepare the example project

    Create a new working directory `java-stateful-function` with the following file structure. Here, pom.xml is the maven configuration file, and Object.java and Main.java are the application code.

    ```bash
    java-stateful-function
    ├── pom.xml
    └── src
        └── main
            └── java
                └── com
                    └── yuanrong
                        └── example
                            ├── Object.java
                            └── Main.java
    ```

    :::{dropdown} pom.xml file content, **please refer to [Install Java SDK](install-yuanrong-java-sdk) and configure dependency yr-api-sdk**
    :chevron: down-up
    :icon: chevron-down

    ```xml
    <?xml version="1.0" encoding="UTF-8"?>

    <project xmlns="http://maven.apache.org/POM/4.0.0"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
        <modelVersion>4.0.0</modelVersion>

        <groupId>org.yuanrong.example</groupId>
        <artifactId>example</artifactId>
        <version>1.0.0</version>

        <properties>
            <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
            <maven.compiler.source>1.8</maven.compiler.source>
            <maven.compiler.target>1.8</maven.compiler.target>
        </properties>

        <dependencies>
            <dependency>
                <!-- Modify version number to your actual version -->
                <groupId>org.yuanrong</groupId>
                <artifactId>yr-api-sdk</artifactId>
                <version>1.0.0</version>
            </dependency>
        </dependencies>

        <build>
            <plugins>
                <plugin>
                    <groupId>org.apache.maven.plugins</groupId>
                    <artifactId>maven-assembly-plugin</artifactId>
                    <executions>
                        <execution>
                            <phase>package</phase>
                            <goals>
                                <goal>single</goal>
                            </goals>
                        </execution>
                    </executions>
                    <configuration>
                        <archive>
                            <manifest>
                                <mainClass>org.yuanrong.example.Main</mainClass>
                            </manifest>
                        </archive>
                        <descriptorRefs>
                            <descriptorRef>jar-with-dependencies</descriptorRef>
                        </descriptorRefs>
                        <appendAssemblyId>false</appendAssemblyId>
                    </configuration>
                </plugin>
            </plugins>
        </build>
    </project>
    ```

    :::
    :::{dropdown} Object.java file content
    :chevron: down-up
    :icon: chevron-down

    ```java
    package org.yuanrong.example;

    // Define stateful function
    public class Object {
        private int value = 0;

        public Object(int value) {
            this.value = value;
        }

        public void save(int value) {
            this.value = value;
        }

        public int get() {
            return this.value;
        }
    }
    ```

    :::
    :::
    :::{dropdown} Main.java file content
    :chevron: down-up
    :icon: chevron-down

    ```java
    package org.yuanrong.example;

    import org.yuanrong.Config;
    import org.yuanrong.api.YR;
    import org.yuanrong.runtime.client.ObjectRef;
    import org.yuanrong.call.InstanceHandler;
    import org.yuanrong.exception.YRException;

    import java.util.HashMap;
    import java.util.ArrayList;
    import java.util.List;

    public class Main {
        public static void main(String[] args) throws YRException {
            // Init only once
            YR.init(new Config());

            // Create three stateful function instances
            List<InstanceHandler> objects = new ArrayList<>();
            for (int i = 0; i < 3; i++) {
                InstanceHandler obj = YR.instance(Object::new).invoke(0);
                objects.add(obj);
            }

            // Asynchronously invoke stateful functions in parallel
            List<ObjectRef> resultsRef = new ArrayList<>();
            for (InstanceHandler obj : objects) {
                obj.function(Object::save).invoke(9);
                ObjectRef resultRef = obj.function(Object::get).invoke();
                resultsRef.add(resultRef);
            }

            for (ObjectRef resultRef : resultsRef) {
                System.out.println(YR.get(resultRef, 30));
            }

            // Destroy stateful function instance
            for (InstanceHandler obj : objects) {
                obj.terminate();
            }

            // Release environmental resources
            YR.Finalize();
        }
    }
    ```

    :::

2. Build

    In the `java-stateful-function` directory, execute the following command to build the application:

    ```bash
    mvn clean package
    ```

    Successful build will generate jar package `example-1.0.0.jar` in the `java-stateful-function/target` directory.

    :::{note}
    Stateful functions may execute on any node in the openYuanrong cluster. Therefore, before running the program, you need to copy the `example-1.0.0.jar` file to the same path on other nodes.
    :::

3. Run the program

    Run the program in the `java-stateful-function` directory, output as follows:

    ```bash
    java -Dyr.codePath=$(pwd)/target -cp target/example-1.0.0.jar org.yuanrong.example.Main
    # 9
    # 9
    # 9
    ```

::::
:::::

(example-project-function-service)=

## Function Service Example Project

### Running Function Service in Host Cluster

Default configuration deployment only supports running stateless and stateful functions. Refer to the following commands to add function service support.

First deploy the master node:

```bash
yr start --master \
-s 'mode.master.frontend=true' -s 'mode.master.function_scheduler=true' -s 'mode.master.meta_service=true'
```

Deploy worker nodes:

```bash
# Replace {http_scheme}, {function_master_ip} and {function_master_port} with corresponding information output when master node is successfully deployed
yr start --master_address {http_scheme}://{function_master_ip}:{function_master_port}
```

Create the same code package directory on all nodes, for example `/opt/mycode/service`, to store the built executable function code.

:::::{tab-set}
::::{tab-item} Python

1. Prepare example code

    Create a file `demo.py` with the following content, and copy it to the code package directory on all nodes.

    ```python
    import datetime

    # Function execution entry, executed on each request, where event parameter is in JSON format
    def handler(event, context):
        print("received request,event content:", event)

        response = ""
        try:
            name = event.get("name")
            # Get configured environment variables, set during function registration and update
            show_date = context.getUserData("show_date")
            if show_date is not None:
                response = "hello " + name + ",today is " + datetime.date.today().strftime('%Y-%m-%d')
            else:
                response = "hello " + name
        except Exception as e:
            print(e)
            response = "please enter your name,for example:{'name':'yuanrong'}"

        return response

    # Function initialization entry, executed once when function instance starts
    def init(context):
        print("function instance initialization completed")

    # Function exit entry, executed once when function instance is destroyed
    def pre_stop():
        print("function instance is being destroyed")
    ```

2. Function registration and invocation

    Use curl tool to register the function. For parameter meanings, see [API documentation](../api/function_service/register_function.md):

    ```bash
    # Replace /opt/mycode/service with your code package directory
    META_SERVICE_ENDPOINT=<meta service component service endpoint, default: http://{master node IP}:31182>
    curl -H "Content-type: application/json" -X POST -i ${META_SERVICE_ENDPOINT}/serverless/v1/functions -d '{"name":"0@myService@python-demo","runtime":"python3.9","handler":"demo.handler","environment":{"show_date":"true"},"extendedHandler":{"initializer":"demo.init","pre_stop":"demo.pre_stop"},"extendedTimeout":{"initializer":30,"pre_stop":10},"kind":"faas","cpu":600,"memory":512,"timeout":60,"storageType":"local","codePath":"/opt/mycode/service"}'
    ```

    The result returns in the following format. Record the value of `functionVersionUrn` field for invocation, which corresponds to `sn:cn:yrk:default:function:0@myService@python-demo:latest` here.

    ```bash
    {"code":0,"message":"SUCCESS","function":{"id":"sn:cn:yrk:default:function:0@myService@python-demo:latest","createTime":"2025-05-29 07:09:34.154 UTC","updateTime":"","functionUrn":"sn:cn:yrk:default:function:0@myService@python-demo","name":"0@myService@python-demo","tenantId":"default","businessId":"yrk","productId":"","reversedConcurrency":0,"description":"","tag":null,"functionVersionUrn":"sn:cn:yrk:default:function:0@myService@python-demo:latest","revisionId":"20250529070934154","codeSize":0,"codeSha256":"","bucketId":"","objectId":"","handler":"demo.handler","layers":null,"cpu":600,"memory":512,"runtime":"python3.9","timeout":60,"versionNumber":"latest","versionDesc":"latest","environment":{"show_date":"true"},"customResources":null,"statefulFlag":0,"lastModified":"","Published":"2025-05-29 07:09:34.154 UTC","minInstance":0,"maxInstance":100,"concurrentNum":100,"funcLayer":[],"status":"","instanceNum":0,"device":{},"created":""}}
    ```

    Use curl tool to invoke the function. For parameter meanings, see [API documentation](../api/function_service/function_invocation.md):

    ```bash
    FRONTEND_ENDPOINT=<frontend component endpoint, default: http://{master node ip}:8888>
    FUNCTION_VERSION_URN=<functionVersionUrn recorded in previous step>
    curl -H "Content-type: application/json" -X POST -i ${FRONTEND_ENDPOINT}/serverless/v1/functions/${FUNCTION_VERSION_URN}/invocations -d '{"name":"yuanrong"}'
    ```

    Result output:

    ```bash
    HTTP/1.1 200 OK
    Content-Type: application/json
    X-Billing-Duration: this is billing duration TODO
    X-Inner-Code: 0
    X-Invoke-Summary:
    X-Log-Result: dGhpcyBpcyB1c2VyIGxvZyBUT0RP
    Date: Tue, 20 May 2025 02:03:09 GMT
    Content-Length: 36
    
    "hello yuanrong,today is 2025-05-20"
    ```

::::
::::{tab-item} C++

1. Prepare example project

    Create a working directory `service-cpp-demo` with the following file structure. The build directory is used to store files generated during compilation. CMakeLists.txt is the configuration file used by CMake build system. demo.cpp is the function code file, we use the open source [nlohmann/json](https://github.com/nlohmann/json){target="_blank"} library to parse JSON.

    ```bash
    service-cpp-demo
    ├── build
    ├── demo.cpp
    └── CMakeLists.txt
    ```

    :::{dropdown} demo.cpp file content
    :chevron: down-up
    :icon: chevron-down

    ```cpp
    #include <string>
    #include <cstdlib>
    #include <ctime>
    #include <nlohmann/json.hpp>

    #include "Runtime.h"
    #include "Function.h"
    #include "yr/yr.h"

    // Function execution entry, executed on each request, where event parameter must be in JSON format, return type can be customized
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

    // Function initialization entry, executed once when function instance starts
    void Initializer(Function::Context &context) {
        std::cout << "function instance initialization completed" << std::endl;
        return;
    }

    // Function exit entry, executed once when function instance is destroyed
    void PreStop(Function::Context &context) {
        std::cout << "function instance is being destroyed" << std::endl;
        return;
    }

    int main(int argc, char *argv[])
    {
        Function::Runtime rt;
        rt.RegisterHandler(HandleRequest);
        rt.RegisterInitializerFunction(Initializer);
        rt.RegisterPreStopFunction(PreStop);
        rt.Start(argc, argv);
        return 0;
    }
    ```

    :::
    :::{dropdown} CMakeLists.txt file content, **need to modify YR_INSTALL_PATH to actual openYuanrong installation path**
    :chevron: down-up
    :icon: chevron-down

    ```cmake
    cmake_minimum_required(VERSION 3.16.1)
    project(demo CXX)

    set(CMAKE_CXX_STANDARD 17)
    set(SOURCE_DIR ${CMAKE_CURRENT_SOURCE_DIR})
    set(BINARY_DIR ${SOURCE_DIR}/build)

    # Replace YR_INSTALL_PATH value with actual openYuanrong installation path
    set(YR_INSTALL_PATH "/usr/local/lib/python3.9/site-packages/yr")
    link_directories(${YR_INSTALL_PATH}/cpp/lib)
    include_directories(
        ${YR_INSTALL_PATH}/cpp/include/faas
        ${YR_INSTALL_PATH}/cpp/include
    )

    add_executable(demo demo.cpp)
    target_link_libraries(demo functionsdk)
    set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${BINARY_DIR})
    ```

    :::

2. Build

    Download [nlohmann/json](https://github.com/nlohmann/json){target="_blank"} for example json-3.12.0.tar.gz version to all openYuanrong nodes, and execute the following commands to install.

    ```bash
    tar -zxvf json-3.12.0.tar.gz
    cd json-3.12.0
    mkdir build
    cd build
    cmake ..
    make
    make install
    ```

    In the `service-cpp-demo/build` directory, execute the following command to build the function:

    ```bash
    cmake ..
    make
    ```

    Successful build will generate binary file `demo` in this directory, copy the file to the code package directory on all nodes.

3. Function registration and invocation

    Use curl tool to register the function. For parameter meanings, see [API documentation](../api/function_service/register_function.md):

    ```bash
    # Replace /opt/mycode/service with your code package directory
    META_SERVICE_ENDPOINT=<meta service component service endpoint, default: http://{master node ip}:31182>
    curl -H "Content-type: application/json" -X POST -i ${META_SERVICE_ENDPOINT}/serverless/v1/functions -d '{"name":"0@myService@cpp-demo","runtime":"posix-custom-runtime","handler":"demo","environment":{"show_date":"true"},"kind":"faas","cpu":600,"memory":512,"timeout":60,"storageType":"local","codePath":"/opt/mycode/service"}'
    ```

    The result returns in the following format. Record the value of `functionVersionUrn` field for invocation, which corresponds to `sn:cn:yrk:default:function:0@myService@cpp-demo:latest` here.

    ```bash
    {"code":0,"message":"SUCCESS","function":{"id":"sn:cn:yrk:default:function:0@myService@cpp-demo:latest","createTime":"2025-05-20 03:43:19.117 UTC","updateTime":"","functionUrn":"sn:cn:yrk:default:function:0@myService@cpp-demo","name":"0@myService@cpp-demo","tenantId":"default","businessId":"yrk","productId":"","reversedConcurrency":0,"description":"","tag":null,"functionVersionUrn":"sn:cn:yrk:default:function:0@myService@cpp-demo:latest","revisionId":"20250520034319117","codeSize":0,"codeSha256":"","bucketId":"","objectId":"","handler":"demo","layers":null,"cpu":600,"memory":512,"runtime":"posix-custom-runtime","timeout":60,"versionNumber":"latest","versionDesc":"latest","environment":{"show_date":"true"},"customResources":null,"statefulFlag":0,"lastModified":"","Published":"2025-05-20 03:43:19.117 UTC","minInstance":0,"maxInstance":100,"concurrentNum":100,"funcLayer":[],"status":"","instanceNum":0,"device":{},"created":""}}
    ```

    Use curl tool to invoke the function. For parameter meanings, see [API documentation](../api/function_service/function_invocation.md):

    ```bash
    FRONTEND_ENDPOINT=<frontend component endpoint, default: http://{master node ip}:8888>
    FUNCTION_VERSION_URN=<functionVersionUrn recorded in previous step>
    curl -H "Content-type: application/json" -X POST -i ${FRONTEND_ENDPOINT}/serverless/v1/functions/${FUNCTION_VERSION_URN}/invocations -d '{"name":"yuanrong"}'
    ```

    Result output:

    ```bash
    HTTP/1.1 200 OK
    Content-Type: application/json
    X-Billing-Duration: this is billing duration TODO
    X-Inner-Code: 0
    X-Invoke-Summary:
    X-Log-Result: this is user log TODO
    Date: Tue, 20 May 2025 03:43:57 GMT
    Content-Length: 35
    
    "hello yuanrong,today is 2025-5-20"
    ```

::::
::::{tab-item} Java

1. Prepare example project

    Create a working directory `service-java-demo` with the following file structure. pom.xml is the maven configuration file, introducing openYuanrong SDK and other dependencies. zip_file.xml is the packaging configuration. Demo.java is the function code file.

    ```bash
    service-java-demo
    ├── pom.xml
    └── src
        └── main
            ├── assembly
            │   └── zip_file.xml
            └── java
                └── com
                    └── yuanrong
                        └── demo
                            └── Demo.java
    ```

    :::{dropdown} Demo.java file content
    :chevron: down-up
    :icon: chevron-down

    ```java
    package org.yuanrong.demo;

    import org.yuanrong.services.runtime.Context;
    import com.google.gson.JsonObject;
    import java.time.LocalDate;

    public class Demo {
        // Function execution entry, executed on each request, where input parameter and function return type can be customized
        public String handler(JsonObject event, Context context) {
            System.out.println("received request,event content:" + event);

            String response = "";
            try {
                String name = event.get("name").getAsString();
                // Get configured environment variables, set during function registration and update
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

        // Function initialization entry, executed once when function instance starts
        public void initializer(Context context) {
            System.out.println("function instance initialization completed");
        }
    }
    ```

    :::
    :::{dropdown} pom.xml file content, **please refer to [Install Java SDK](install-yuanrong-java-sdk) and configure dependency faas-function-sdk**
    :chevron: down-up
    :icon: chevron-down

    ```xml
    <?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
        <modelVersion>4.0.0</modelVersion>

        <groupId>org.yuanrong.demo</groupId>
        <artifactId>demo</artifactId>
        <version>1.0.0</version>

        <properties>
            <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
            <maven.compiler.source>1.8</maven.compiler.source>
            <maven.compiler.target>1.8</maven.compiler.target>
            <maven.build.timestamp.format>yyyyMMddHHmmss</maven.build.timestamp.format>
            <package.finalName>demo</package.finalName>
            <package.outputDirectory>target</package.outputDirectory>
        </properties>

        <dependencies>
            <dependency>
                <!-- Modify version number to your actual version -->
                <groupId>org.yuanrong</groupId>
                <artifactId>faas-function-sdk</artifactId>
                <version>1.0.0</version>
            </dependency>
            <dependency>
                <groupId>com.google.code.gson</groupId>
                <artifactId>gson</artifactId>
                <version>2.9.0</version>
            </dependency>
        </dependencies>

        <build>
            <plugins>
                <!-- Configure the following packaging method -->
                <plugin>
                    <groupId>org.apache.maven.plugins</groupId>
                    <artifactId>maven-assembly-plugin</artifactId>
                    <version>2.2</version>
                    <configuration>
                        <archive>
                            <manifest>
                                <addDefaultImplementationEntries>true</addDefaultImplementationEntries>
                            </manifest>
                        </archive>
                        <appendAssemblyId>false</appendAssemblyId>
                    </configuration>
                    <executions>
                        <execution>
                            <id>auto-deploy</id>
                            <phase>package</phase>
                            <goals>
                                <goal>single</goal>
                            </goals>
                            <configuration>
                                <descriptors>
                                    <descriptor>src/main/assembly/zip_file.xml</descriptor>
                                </descriptors>
                                <finalName>${package.finalName}</finalName>
                                <outputDirectory>${package.outputDirectory}</outputDirectory>
                                <archiverConfig>
                                    <directoryMode>0700</directoryMode>
                                    <fileMode>0600</fileMode>
                                    <defaultDirectoryMode>0700</defaultDirectoryMode>
                                </archiverConfig>
                            </configuration>
                        </execution>
                    </executions>
                </plugin>
            </plugins>
        </build>
    </project>
    ```

    :::
    :::{dropdown} zip_file.xml file content
    :chevron: down-up
    :icon: chevron-down

    ```xml
    <?xml version="1.0" encoding="UTF-8"?>

    <assembly xmlns="http://maven.apache.org/plugins/maven-assembly-plugin/assembly/1.1.2">

        <id>auto-deploy</id>
        <baseDirectory/>
        <formats>
            <format>zip</format>
        </formats>

        <fileSets>
            <fileSet>
                <directory>src/main/resources/</directory>
                <outputDirectory>config</outputDirectory>
                <includes>
                    <include>**</include>
                </includes>
                <fileMode>0600</fileMode>
                <directoryMode>0700</directoryMode>
            </fileSet>

        </fileSets>

        <dependencySets>
            <dependencySet>
                <outputDirectory>lib</outputDirectory>
                <scope>runtime</scope>
            </dependencySet>
        </dependencySets>
    </assembly>
    ```

    :::

2. Build

    In the `service-java-demo` directory, execute the following command to build:

    ```bash
    mvn clean package
    ```

    Successful build will generate compressed package `demo.zip` in the `service-java-demo/target` directory, copy the file to the code package directory on all nodes and extract using command `unzip demo.zip`.

3. Function registration and invocation

    Use curl tool to register the function. For parameter meanings, see [API documentation](../api/function_service/register_function.md):

    ```bash
    # Replace /opt/mycode/service with your code package directory
    META_SERVICE_ENDPOINT=<meta service component service endpoint, default: http://{master node ip}:31182>
    curl -H "Content-type: application/json" -X POST -i ${META_SERVICE_ENDPOINT}/serverless/v1/functions -d '{"name":"0@myService@java-demo","runtime":"java8","handler":"org.yuanrong.demo.Demo::handler","environment":{"show_date":"true"},"extendedHandler":{"initializer":"org.yuanrong.demo.Demo::initializer"},"extendedTimeout":{"initializer":30},"kind":"faas","cpu":600,"memory":512,"timeout":60,"storageType":"local","codePath":"/opt/mycode/service"}'
    ```

    The result returns in the following format. Record the value of `functionVersionUrn` field for invocation, which corresponds to `sn:cn:yrk:default:function:0@myService@java-demo:latest` here.

    ```bash
    {"code":0,"message":"SUCCESS","function":{"id":"sn:cn:yrk:default:function:0@myService@java-demo:latest","createTime":"2025-05-20 06:26:42.396 UTC","updateTime":"","functionUrn":"sn:cn:yrk:default:function:0@myService@java-demo","name":"0@myService@java-demo","tenantId":"default","businessId":"yrk","productId":"","reversedConcurrency":0,"description":"","tag":null,"functionVersionUrn":"sn:cn:yrk:default:function:0@myService@java-demo:latest","revisionId":"20250520062642396","codeSize":0,"codeSha256":"","bucketId":"","objectId":"","handler":"org.yuanrong.demo.Demo::handler","layers":null,"cpu":600,"memory":512,"runtime":"java8","timeout":60,"versionNumber":"latest","versionDesc":"latest","environment":{"show_date":"true"},"customResources":null,"statefulFlag":0,"lastModified":"","Published":"2025-05-20 06:26:42.396 UTC","minInstance":0,"maxInstance":100,"concurrentNum":100,"funcLayer":[],"status":"","instanceNum":0,"device":{},"created":""}}
    ```

    Use curl tool to invoke the function. For parameter meanings, see [API documentation](../api/function_service/function_invocation.md):

    ```bash
    FRONTEND_ENDPOINT=<frontend component endpoint, default: http://{master node ip}:8888>
    FUNCTION_VERSION_URN=<functionVersionUrn recorded in previous step>
    curl -H "Content-type: application/json" -X POST -i ${FRONTEND_ENDPOINT}/serverless/v1/functions/${FUNCTION_VERSION_URN}/invocations -d '{"name":"yuanrong"}'
    ```

    Result output:

    ```bash
    HTTP/1.1 200 OK
    Content-Type: application/json
    X-Billing-Duration: this is billing duration TODO
    X-Inner-Code: 0
    X-Invoke-Summary:
    X-Log-Result: dGhpcyBpcyB1c2VyIGxvZyBUT0RP
    Date: Tue, 20 May 2025 06:27:49 GMT
    Content-Length: 36
    
    "hello yuanrong,today is 2025-05-20"
    ```

::::
:::::

(example-project-function-K8s-service)=

### Running Function Service in K8s Cluster

To run function service in K8s, you need to first create a resource pool. If you have already created it when deploying openYuanrong, you can skip this step. First create a create_pool.json file with the following content:

```json
{
    "pools": [
        {
            "id": "pool-600-512",
            "size": 1,
            "group": "rg1",
            "reuse": false,
            "resources": {
                "limits": {
                    "cpu": "600m",
                    "memory": "512Mi"
                },
                "requests": {
                    "cpu": "600m",
                    "memory": "512Mi"
                }
            }
        }
    ]
}
```

Use curl tool to create the resource pool. For parameter meanings, see [API documentation](../../deploy/deploy_on_k8s/api/create_pod_pool.md):

```bash
META_SERVICE_ENDPOINT=<meta service component service endpoint, default: http://{master node IP}:31182>
curl -X POST -i ${META_SERVICE_ENDPOINT}/serverless/v1/podpools -H 'Content-Type: application/json' -d @create_pool.json
```

The result returns in the following format.
    
```json
{
  "code":0,
  "message": "",
  "result": {
    "failed_pools": null
  }
}
```

:::::{tab-set}
::::{tab-item} Python

1. Prepare example code

    Create a file demo.py with the following content.

    ```python
    import datetime
    # Function execution entry, executed on each request, where event parameter is in JSON format
    def handler(event, context):
        print("received request,event content:", event)

        response = ""
        try:
            name = event.get("name")
            # Get configured environment variables, set during function registration and update
            show_date = context.getUserData("show_date")
            if show_date is not None:
                response = "hello " + name + ",today is " + datetime.date.today().strftime('%Y-%m-%d')
            else:
                response = "hello " + name
        except Exception as e:
            print(e)
            response = "please enter your name,for example:{'name':'yuanrong'}"
    
        return response

    # Function initialization entry, executed once when function instance starts
    def init(context):
        print("function instance initialization completed")
    
    # Function exit entry, executed once when function instance is destroyed
    def pre_stop():
        print("function instance is being destroyed")    
    ```

    Package into demo.zip and use [MinIO Client](tools-minio-client) to upload the code package to MinIO service in openYuanrong cluster.
        
    ```bash
    zip demo.zip demo.py
    mc mb mys3/demo-bucket
    mc cp ./demo.zip mys3/demo-bucket/demo.zip
    ```

2. Function registration and invocation

    Create a file create_func.json with the following content.

    ```json
     {
        "name": "0@myService@python-demo",
        "handler": "demo.handler",
        "extendedHandler":{"initializer":"demo.init","pre_stop":"demo.pre_stop"},
          "environment":{"show_date":"true"},
          "runtime": "python3.9",
          "cpu": 600,
          "memory": 512,
          "timeout": 30,
          "currentNum": "100",
          "kind" : "faas",
          "storageType": "s3",
          "s3CodePath": {
            "bucketId": "demo-bucket",
            "objectId": "demo.zip",
            "bucketUrl": "http://{Your MinIO Address:30110}"
          }  
     }
    ```
    
    Register the function using curl tool. For parameter meanings, see [API documentation](../api/function_service/register_function.md):
        
    ```bash 
    META_SERVICE_ENDPOINT=<meta service component service endpoint, default: http://{master node IP}:31182>
    curl -X POST -i ${META_SERVICE_ENDPOINT}/serverless/v1/functions \
            -H 'Content-Type: application/json' -H 'x-storage-type: local' \
            -d @create_func.json
        
    ```
    
    The result format is as follows. Record the value of `functionVersionUrn` field for invocation, which corresponds to `sn:cn:yrk:default:function:0@myService@python-demo:latest` here.
        
    ```json
    {"code":0,"message":"SUCCESS","function":{"id":"sn:cn:yrk:default:function:0@myService@python-demo:latest","createTime":"2026-01-20 01:57:36.938 UTC","updateTime":"","functionUrn":"sn:cn:yrk:default:function:0@myService@python-demo","name":"0@myService@python-demo","tenantId":"default","businessId":"yrk","productId":"","reversedConcurrency":0,"description":"","tag":null,"functionVersionUrn":"sn:cn:yrk:default:function:0@myService@python-demo:latest","revisionId":"20260120015736938","codeSize":0,"extendedHandler":{"initializer":"demo.init","pre_stop":"demo.pre_stop"},"codeSha256":"","bucketId":"demo-bucket","objectId":"demo.zip","handler":"demo.handler","layers":null,"cpu":600,"memory":512,"runtime":"python3.9","timeout":30,"versionNumber":"latest","versionDesc":"latest","environment":{"show_date":"true"},"customResources":null,"statefulFlag":0,"lastModified":"","Published":"2016-01-20 01:57:36.936 UTC","minInstance":1,"maxInstance":100,"concurrentNum":100,"funcLayer":[],"status":"","instanceNum":0,"device":{},"created":""}}
    ```

    Use curl tool to invoke the function. For parameter meanings, see [API documentation](../api/function_service/function_invocation.md): 
    
    ```bash
    FRONTEND_ENDPOINT=<frontend component endpoint, default: http://{master node ip}:8888>
    # Set functionVersionUrn environment variable, based on the functionVersionUrn returned when creating the function earlier
    curl -H "Content-type: application/json" -X POST \
         -i ${FRONTEND_ENDPOINT}/serverless/v1/functions/${functionVersionUrn}/invocations \
         -d {\"name\":\"openyuanrong\"}
    ```
    
    Result output: "hello yuanrong,today is 2026-01-20"

::::
::::{tab-item} C++

1. Prepare example project

    Create a working directory `service-cpp-demo` with the following file structure. The build directory is used to store files generated during compilation. CMakeLists.txt is the configuration file used by CMake build system. demo.cpp is the function code file, we use the open source [nlohmann/json](https://github.com/nlohmann/json){target="_blank"} library to parse JSON.

    ```bash
    service-cpp-demo
    ├── build
    ├── demo.cpp
    └── CMakeLists.txt
    ```

    :::{dropdown} demo.cpp file content
    :chevron: down-up
    :icon: chevron-down

    ```cpp
    #include <string>
    #include <cstdlib>
    #include <ctime>
    #include <nlohmann/json.hpp>

    #include "Runtime.h"
    #include "Function.h"
    #include "yr/yr.h"

    // Function execution entry, executed on each request, where event parameter must be in JSON format, return type can be customized
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

    // Function initialization entry, executed once when function instance starts
    void Initializer(Function::Context &context) {
        std::cout << "function instance initialization completed" << std::endl;
        return;
    }

    // Function exit entry, executed once when function instance is destroyed
    void PreStop(Function::Context &context) {
        std::cout << "function instance is being destroyed" << std::endl;
        return;
    }

    int main(int argc, char *argv[])
    {
        Function::Runtime rt;
        rt.RegisterHandler(HandleRequest);
        rt.RegisterInitializerFunction(Initializer);
        rt.RegisterPreStopFunction(PreStop);
        rt.Start(argc, argv);
        return 0;
    }
    ```

    :::
    :::{dropdown} CMakeLists.txt file content, **need to modify YR_INSTALL_PATH to actual openYuanrong installation path**
    :chevron: down-up
    :icon: chevron-down

    ```cmake
    cmake_minimum_required(VERSION 3.16.1)
    project(demo CXX)

    set(CMAKE_CXX_STANDARD 17)
    set(SOURCE_DIR ${CMAKE_CURRENT_SOURCE_DIR})
    set(BINARY_DIR ${SOURCE_DIR}/build)

    # Replace YR_INSTALL_PATH value with actual openYuanrong installation path
    set(YR_INSTALL_PATH "/usr/local/lib/python3.9/site-packages/yr")
    link_directories(${YR_INSTALL_PATH}/cpp/lib)
    include_directories(
        ${YR_INSTALL_PATH}/cpp/include/faas
        ${YR_INSTALL_PATH}/cpp/include
    )

    add_executable(demo demo.cpp)
    target_link_libraries(demo functionsdk)
    set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${BINARY_DIR})
    ```

    :::

2. Build

    Download [nlohmann/json](https://github.com/nlohmann/json){target="_blank"} for example json-3.12.0.tar.gz version to all openYuanrong nodes, and execute the following commands to install.

    ```bash
    tar -zxvf json-3.12.0.tar.gz
    cd json-3.12.0
    mkdir build
    cd build
    cmake ..
    make
    make install
    ```

    In the `service-cpp-demo/build` directory, execute the following command to build the function:

    ```bash
    cmake ..
    make
    ```

    Successful build will generate binary file `demo` in this directory, package into demo.zip and use [Minio Client](../../reference/development-tools.md) to upload to MinIO.
        
    ```bash
    zip demo.zip demo
    mc mb mys3/demo-bucket
    mc cp ./demo.zip mys3/demo-bucket/demo.zip
    ```

3. Function registration and invocation

    Create a file create_func.json with the following content.

    ```json
    {
        "name": "0@myService@cpp-demo",
        "runtime": "posix-custom-runtime",
        "handler": "demo",
        "environment": {
            "show_date": "true"
        },
        "kind": "faas",
        "cpu": 600,
        "memory": 512,
        "timeout": 60,
        "storageType": "s3",
        "s3CodePath": {
            "bucketId": "demo-bucket",
            "objectId": "demo.zip",
            "bucketUrl": "http://{Your MinIO Address:9000}"
        }
    }   
    ```

    Use curl tool to register the function. For parameter meanings, see [API documentation](../api/function_service/register_function.md):

    ```bash
    # Replace /opt/mycode/service with your code package directory
    META_SERVICE_ENDPOINT=<meta service component service endpoint, default: http://{master node ip}:31182>
    curl -H "Content-type: application/json" -X POST -i ${META_SERVICE_ENDPOINT}/serverless/v1/functions -H 'Content-Type: application/json' \
         -H 'x-storage-type: local' \
         -d @create_func.json
    ```

    The result returns in the following format. Record the value of `functionVersionUrn` field for invocation, which corresponds to `sn:cn:yrk:default:function:0@myService@cpp-demo:latest` here.

    ```bash
    {"code":0,"message":"SUCCESS","function":{"id":"sn:cn:yrk:default:function:0@myService@cpp-demo:latest","createTime":"2025-05-20 03:43:19.117 UTC","updateTime":"","functionUrn":"sn:cn:yrk:default:function:0@myService@cpp-demo","name":"0@myService@cpp-demo","tenantId":"default","businessId":"yrk","productId":"","reversedConcurrency":0,"description":"","tag":null,"functionVersionUrn":"sn:cn:yrk:default:function:0@myService@cpp-demo:latest","revisionId":"20250520034319117","codeSize":0,"codeSha256":"","bucketId":"demo-bucket","objectId":"demo.zip","handler":"demo","layers":null,"cpu":600,"memory":512,"runtime":"posix-custom-runtime","timeout":60,"versionNumber":"latest","versionDesc":"latest","environment":{"show_date":"true"},"customResources":null,"statefulFlag":0,"lastModified":"","Published":"2025-05-20 03:43:19.117 UTC","minInstance":0,"maxInstance":100,"concurrentNum":100,"funcLayer":[],"status":"","instanceNum":0,"device":{},"created":""}}
    ```

    Use curl tool to invoke the function. For parameter meanings, see [API documentation](../api/function_service/function_invocation.md):

    ```bash
    FRONTEND_ENDPOINT=<frontend component endpoint, default: http://{master node ip}:8888>
    FUNCTION_VERSION_URN=<functionVersionUrn recorded in previous step>
    curl -H "Content-type: application/json" -X POST -i ${FRONTEND_ENDPOINT}/serverless/v1/functions/${FUNCTION_VERSION_URN}/invocations -d '{"name":"yuanrong"}'
    ```

    Result output:

    ```bash
    HTTP/1.1 200 OK
    Content-Type: application/json
    X-Billing-Duration: this is billing duration TODO
    X-Inner-Code: 0
    X-Invoke-Summary:
    X-Log-Result: this is user log TODO
    Date: Tue, 26 Jan 2026 11:31:57 GMT
    Content-Length: 35
    
    "hello yuanrong,today is 2026-1-26"
    ```

::::

::::{tab-item} Java

1. Prepare example project

    Create a working directory `service-java-demo` with the following file structure. pom.xml is the maven configuration file, introducing openYuanrong SDK and other dependencies. zip_file.xml is the packaging configuration. Demo.java is the function code file.

    ```bash
    service-java-demo
    ├── pom.xml
    └── src
        └── main
            ├── assembly
            │   └── zip_file.xml
            └── java
                └── com
                    └── yuanrong
                        └── demo
                            └── Demo.java
    ```

    :::{dropdown} Demo.java file content
    :chevron: down-up
    :icon: chevron-down

    ```java
    package org.yuanrong.demo;

    import org.yuanrong.services.runtime.Context;
    import com.google.gson.JsonObject;
    import java.time.LocalDate;

    public class Demo {
        // Function execution entry, executed on each request, where input parameter and function return type can be customized
        public String handler(JsonObject event, Context context) {
            System.out.println("received request,event content:" + event);

            String response = "";
            try {
                String name = event.get("name").getAsString();
                // Get configured environment variables, set during function registration and update
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

        // Function initialization entry, executed once when function instance starts
        public void initializer(Context context) {
            System.out.println("function instance initialization completed");
        }
    }
    ```

    :::
    :::{dropdown} pom.xml file content, **please refer to [Install Java SDK](install-yuanrong-java-sdk) and configure dependency faas-function-sdk**
    :chevron: down-up
    :icon: chevron-down

    ```xml
    <?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
        <modelVersion>4.0.0</modelVersion>

        <groupId>org.yuanrong.demo</groupId>
        <artifactId>demo</artifactId>
        <version>1.0.0</version>

        <properties>
            <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
            <maven.compiler.source>1.8</maven.compiler.source>
            <maven.compiler.target>1.8</maven.compiler.target>
            <maven.build.timestamp.format>yyyyMMddHHmmss</maven.build.timestamp.format>
            <package.finalName>demo</package.finalName>
            <package.outputDirectory>target</package.outputDirectory>
        </properties>

        <dependencies>
            <dependency>
                <!-- Modify version number to your actual version -->
                <groupId>org.yuanrong</groupId>
                <artifactId>faas-function-sdk</artifactId>
                <version>1.0.0</version>
            </dependency>
            <dependency>
                <groupId>com.google.code.gson</groupId>
                <artifactId>gson</artifactId>
                <version>2.9.0</version>
            </dependency>
        </dependencies>

        <build>
            <plugins>
                <!-- Configure the following packaging method -->
                <plugin>
                    <groupId>org.apache.maven.plugins</groupId>
                    <artifactId>maven-assembly-plugin</artifactId>
                    <version>2.2</version>
                    <configuration>
                        <archive>
                            <manifest>
                                <addDefaultImplementationEntries>true</addDefaultImplementationEntries>
                            </manifest>
                        </archive>
                        <appendAssemblyId>false</appendAssemblyId>
                    </configuration>
                    <executions>
                        <execution>
                            <id>auto-deploy</id>
                            <phase>package</phase>
                            <goals>
                                <goal>single</goal>
                            </goals>
                            <configuration>
                                <descriptors>
                                    <descriptor>src/main/assembly/zip_file.xml</descriptor>
                                </descriptors>
                                <finalName>${package.finalName}</finalName>
                                <outputDirectory>${package.outputDirectory}</outputDirectory>
                                <archiverConfig>
                                    <directoryMode>0700</directoryMode>
                                    <fileMode>0600</fileMode>
                                    <defaultDirectoryMode>0700</defaultDirectoryMode>
                                </archiverConfig>
                            </configuration>
                        </execution>
                    </executions>
                </plugin>
            </plugins>
        </build>
    </project>
    ```

    :::
    :::{dropdown} zip_file.xml file content
    :chevron: down-up
    :icon: chevron-down

    ```xml
    <?xml version="1.0" encoding="UTF-8"?>

    <assembly xmlns="http://maven.apache.org/plugins/maven-assembly-plugin/assembly/1.1.2">

        <id>auto-deploy</id>
        <baseDirectory/>
        <formats>
            <format>zip</format>
        </formats>

        <fileSets>
            <fileSet>
                <directory>src/main/resources/</directory>
                <outputDirectory>config</outputDirectory>
                <includes>
                    <include>**</include>
                </includes>
                <fileMode>0600</fileMode>
                <directoryMode>0700</directoryMode>
            </fileSet>

        </fileSets>

        <dependencySets>
            <dependencySet>
                <outputDirectory>lib</outputDirectory>
                <scope>runtime</scope>
            </dependencySet>
        </dependencySets>
    </assembly>
    ```

    :::

2. Build

    In the `service-java-demo` directory, execute the following command to build:

    ```bash
    mvn clean package
    ```

    Successful build will generate compressed package `demo.zip` in the `service-java-demo/target` directory, and use [Minio Client](../../reference/development-tools.md) to upload to MinIO.
        
    ```bash
    mc mb mys3/demo-bucket
    mc cp ./demo.zip mys3/demo-bucket/demo.zip
    ```

3. Function registration and invocation

    Use curl tool to register the function. For parameter meanings, see [API documentation](../api/function_service/register_function.md):

    Create a file create_func.json with the following content.

    ```json
    {
        "name": "0@myService@java-demo",
        "runtime": "java8",
        "handler": "org.yuanrong.demo.Demo::handler",
        "environment": {
            "show_date": "true"
        },
        "extendedHandler": {
            "initializer": "org.yuanrong.demo.Demo::initializer"
        },
        "extendedTimeout": {
            "initializer": 30
        },
        "kind": "faas",
        "cpu": 600,
        "memory": 512,
        "timeout": 60,
        "storageType": "s3",
        "s3CodePath": {
            "bucketId": "demo-bucket",
            "objectId": "demo.zip",
            "bucketUrl": "http://{Your MinIO Address:9000}"
        }
    }
    ```

    ```bash
    # Replace /opt/mycode/service with your code package directory
    META_SERVICE_ENDPOINT=<meta service component service endpoint, default: http://{master node ip}:31182>
    curl -H "Content-type: application/json" -X POST -i ${META_SERVICE_ENDPOINT}/serverless/v1/functions -H 'Content-Type: application/json' \
         -H 'x-storage-type: local' \
         -d @create_func.json
    ```

    The result returns in the following format. Record the value of `functionVersionUrn` field for invocation, which corresponds to `sn:cn:yrk:default:function:0@myService@java-demo:latest` here.

    ```bash
    {"code":0,"message":"SUCCESS","function":{"id":"sn:cn:yrk:default:function:0@myService@java-demo:latest","createTime":"2025-05-20 06:26:42.396 UTC","updateTime":"","functionUrn":"sn:cn:yrk:default:function:0@myService@java-demo","name":"0@myService@java-demo","tenantId":"default","businessId":"yrk","productId":"","reversedConcurrency":0,"description":"","tag":null,"functionVersionUrn":"sn:cn:yrk:default:function:0@myService@java-demo:latest","revisionId":"20250520062642396","codeSize":0,"codeSha256":"","bucketId":"demo-bucket","objectId":"demo.zip","handler":"org.yuanrong.demo.Demo::handler","layers":null,"cpu":600,"memory":512,"runtime":"java8","timeout":60,"versionNumber":"latest","versionDesc":"latest","environment":{"show_date":"true"},"customResources":null,"statefulFlag":0,"lastModified":"","Published":"2025-05-20 06:26:42.396 UTC","minInstance":0,"maxInstance":100,"concurrentNum":100,"funcLayer":[],"status":"","instanceNum":0,"device":{},"created":""}}
    ```

    Use curl tool to invoke the function. For parameter meanings, see [API documentation](../api/function_service/function_invocation.md):

    ```bash
    FRONTEND_ENDPOINT=<frontend component endpoint, default: http://{master node ip}:8888>
    FUNCTION_VERSION_URN=<functionVersionUrn recorded in previous step>
    curl -H "Content-type: application/json" -X POST -i ${FRONTEND_ENDPOINT}/serverless/v1/functions/${FUNCTION_VERSION_URN}/invocations -d '{"name":"yuanrong"}'
    ```

    Result output:

    ```bash
    HTTP/1.1 200 OK
    Content-Type: application/json
    X-Billing-Duration: this is billing duration TODO
    X-Inner-Code: 0
    X-Invoke-Summary:
    X-Log-Result: dGhpcyBpcyB1c2VyIGxvZyBUT0RP
    Date: Tue, 26 Jan 2026 11:30:49 GMT
    Content-Length: 36
    
    "hello yuanrong,today is 2026-1-26"
    ```

::::
:::::
