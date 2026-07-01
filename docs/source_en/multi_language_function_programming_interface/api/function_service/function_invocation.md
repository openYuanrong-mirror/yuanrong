# Invoke Service

## Description

Synchronously invoke a function service.

## URI

POST /serverless/v1/functions/{functionVersionURN}/invocations

Path Parameters:

| **Parameter** | **Required** | **Type** | **Description** |
| ---------- | ----- | ---------- | ------------------------- |
| functionVersionURN | Yes | String | Function version URN. |

## Request Parameters

Request Header Parameters

| **Parameter** | **Required** | **Type** | **Description** |
| ---------- | ----- | ---------- | ------------------------- |
| Content-Type               | Yes | string | Message body type.<br> **Value:** It is recommended to use application/json. |
| X-Instance-Cpu             | No | string | CPU required for the function instance. |
| X-Instance-Memory          | No | string | Memory required for the function instance. |
| X-Instance-Custom-Resource | No | string | Custom resources required for the function instance. |
| X-Pool-Label               | No | string | Resource pool label for affinity scheduling of the function instance. |
| X-Instance-Label           | No | string | Run on function instances with this label. |
| X-Instance-Session         | No | string | Specify an instance session for invocation; the session is uniquely bound to the instance.<br> Example: {"sessionID":"abc","sessionTTL":10,"concurrency": 5}, where sessionID does not exceed 63 characters, sessionTTL is not less than 0 (unit: seconds), and concurrency cannot exceed the concurrentNum configured in the function. When concurrency is -1, it indicates exclusive use of the entire function instance. |
| X-Session-Context            | No | string | Specify the Session Context. This header only takes effect when the function metadata `enableSessionCtx` is ``true``.<br> Example: {"sessionCtx":"ctx-a"}. For the same function, requests with different `sessionCtx` values do not reuse the same function instance. When the header is missing or `sessionCtx` is empty, the default empty-string context is used. The function process can read the current Session Context ID from the `YR_SESSION_CTX_ID` environment variable. |

<br> Request Body Parameters

Custom format defined by the user function.

## Response Parameters

Custom format defined by the user function.

## Request Example

POST {[frontend endpoint](api-frontend-endpoint)}/serverless/v1/functions/{functionVersionURN}/invocations

```json
{
    "name":"yuanrong"
}
```

For functions with `enableSessionCtx` enabled, specify the Session Context through `X-Session-Context` during invocation:

```bash
curl -X POST "{frontend endpoint}/serverless/v1/functions/{functionVersionURN}/invocations" \
  -H "Content-Type: application/json" \
  -H 'X-Session-Context: {"sessionCtx":"ctx-a"}' \
  -d '{"name":"yuanrong"}'
```

## Response Example

Status Code: 200

Indicates successful function invocation.

```text
"hello yuanrong"
```

## Error Codes

See [Error Codes](../error_code.md)
