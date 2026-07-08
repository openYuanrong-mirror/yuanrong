# Streaming Response

In large language model inference scenarios, streaming returns can gradually send results to the client while the model generates text, achieving real-time interactive experience.

Function services support streaming response data. openYuanrong provides two streaming response REST APIs: [Subscribe to Stream Service](../../api/function_service/stream_invocation.md) and [Invoke Service](../../api/function_service/function_invocation.md) with streaming returns.

## Subscribe to Stream Service

Streams produced using the data stream API in the standalone program distributed parallelization interface can be consumed by calling the [Subscribe to Stream Service](../../api/function_service/stream_invocation.md) REST API. When using this interface, note the following:

- Stream producers and subscribers must maintain the same stream name.
- Ensure in business logic that streams are subscribed before producing data to avoid produced data not being fully consumed.
- It is recommended that stream producers and subscribers negotiate specific terminators to express stream data transmission completion, facilitating subscribers to actively close after consuming data.

View the complete usage example in [Using Streams in Function Services](../../examples/use_stream.md).

## Streaming Returns When Invoking Services

Streaming returns when invoking openYuanrong services are implemented based on the SSE (Server-Send Events) protocol. In function services, associate streams through the `context.getStream()` interface in the context interface to send stream data. An example of a function service with streaming returns is as follows.

:::::{tab-set}
::::{tab-item} Python

```python
import json

def handler(event, context):
    data = {"event":"this is a stream"}
    context.get_stream().write(json.dumps(data))
    return 'ok'
```

::::
::::{tab-item} Java

```java
package org.yuanrong.demo;

import org.yuanrong.services.runtime.Context;
import org.yuanrong.services.runtime.action.Stream;
import com.google.gson.JsonObject;

public class Demo {
    public String handler(JsonObject jsonObject, Context context) throws Exception {
        try {
            Stream stream = context.getStream();
            JsonObject obj = new JsonObject();
            obj.addProperty("event","this is a stream");
            stream.write(obj);
        } catch (Exception e) {
            System.out.println("executor exception occurred");
        }
        return "ok";
    }
}
```

::::
:::::

When invoking a function service, you need to add the `Accept: text/event-stream` field to the request header.

:::{Note}

Streaming response requires deploying openYuanrong with function service support and configuring `frontend.args.enableEvent=true`.

:::
