# Update Function

## Description

This API is used to update a function in the openYuanrong cluster by calling the meta_service interface.

## Constraints

None

## URI

`PUT /serverless/v1/functions/{name}`

| **Name**     | **Type**  | **Required**  | **Description**               |
| ----------- | -------------------- | ------------------------- | ------------------------- |
| name | String | Yes | Function name |

## Request Parameters

### Request Header Parameters

| **Parameter**     | **Type**             | **Required**                   | **Description** |
| ----------- | -------------------- | ------------------------- | ----------- |
| Content-Type | string | Yes | Message body type, it is recommended to use ``application/json``. |
| x-storage-type | string | Yes | Code package upload method, values: ``local``, ``s3``. If code is not uploaded via the interface, default is ``local``. |

### Request Body Parameters

| **Name**     | **Type**  | **Required**  | **Description**               |
| ----------- | -------------------- | ------------------------- | ------------------------- |
| revisionId | String| Yes | Function revisionId, must be consistent with before update, can be obtained through query interfaces, such as: query function list, query all versions of function, query specific version of function. |
| description | String | No | Function description.  |
| handler | String | No | Invocation handler. |
| kind | String | Yes | Function type, values ``faas`` or ``yrlib``, this parameter cannot be updated. |
| cpu | int | Yes | Function CPU size, unit: `m (millicores)`. |
| memory | int | Yes | Function MEM size, unit: `MB`. |
| timeout | int | Yes | Function invocation timeout.<br> Maximum value ``8640000 s``. When the parameter exceeds the maximum, it is automatically set to the maximum. If not filled, the default is ``900 s``.|
| customResources | map | No | Function custom resources.<br> **Constraints**: key-value format, key is string, value is float type.|
| environment | map | No | Function environment variables.<br> **Constraints**: key-value format, both key and value are string.|
| extendedHandler | ExtendedHandler | No | Configure init handler information. |
| extendedTimeout | ExtendedTimeout | No | Configure init timeout information. |
| minInstance | String | No | Minimum number of instances (used by function service).|
| maxInstance | String | No | Maximum number of instances (used by function service). |
| concurrentNum | String | No | Instance concurrency (used by function service). |
| storageType | String | No | Code package storage type.<br> Values: ``local``, ``s3``, ``copy``, it is recommended to fill in.|
| codePath | String | No | Code package local path. Effective when `storageType` is configured as ``local`` or ``copy``. |
| s3CodePath | S3Object | No | Code package S3 path, effective when `storageType` is configured as ``s3``. |
| poolId | String | No | Custom affinity pool ID. When function instance creation resources are insufficient (or affinity conditions are not met), the kernel creates a POD with the specified poolID for instance scheduling.<br> **Constraints**: Only effective for function services; configuration constraints are consistent with the create pool interface.                                                                |
| resourceAffinitySelectors | ResourceAffinitySelector | No | Function scheduling affinity and priority configuration. |
| enableAgentSession | boolean | No | Whether to enable AI Agent session. After enabling, supports `waitForNotify`/`notify` SDK and session affinity scheduling. Default is ``false``. |
| enableSessionCtx | boolean | No | Whether to enable Session Context instance isolation. After enabling, invocation requests can specify `sessionCtx` through the `X-Session-Context` header. Function instances are not reused across different `sessionCtx` values. Default is ``false``. |

:::{Note}

When `storageType` is configured as ``copy``, openYuanrong will copy the code package in codePath to other directories in the container for caching. Compared to the local method, this can reduce performance degradation caused by disk IO when loading code. It is recommended to set directory permissions to ``755`` to ensure that the sn user in the container has permission to copy.

:::

#### S3Object Introduction

| **Name**     | **Type**  | **Required**  | **Description**               |
| ----------- | -------------------- | ------------------------- | ------------------------- |
| bucketId | String | No |  Bucket name.|
| objectId | String | No |  Storage object ID.|
| bucketUrl | String | No |  Storage URL.|
| sha512 | String | No |  Code package sha512 value, can be obtained by executing the sha512sum command.|

#### ExtendedHandler Introduction

| **Name**      | **Type**  | **Required**  | **Description**                         |
|-------------| -------------------- | ------------------------- |--------------------------------|
| initializer | String | No | Initialization interface, configured as needed for function service.    |
| pre_stop     | String | No | Stop interface, exit logic executed before function stops, configured as needed for function service. |

#### ExtendedTimeout Introduction

| **Name**         | **Type**  | **Required**  | **Description**                         |
|----------------| -------------------- | ------------------------- |--------------------------------|
| initializer    | int | No | Initialization timeout, configured as needed for function service.            |
| pre_stop | int | No | Function stop timeout, maximum value ``180s``, configured as needed for function service. |

:::{Note}

When `storageType` is configured as ``copy`` or ``s3``, the `init` timeout needs to include the execution time of the `init handler` and the code package copy or download time. For extra large code packages, it is recommended to set a larger timeout.

:::

#### ResourceAffinitySelector Introduction

| **Name**     | **Type**  | **Required**  | **Description**               |
| ----------- | -------------------- | ------------------------- | ------------------------- |
| group | String | No |  Resource group name.|
| priority | int | No | Priority (reserved field).|

## Response Parameters

| **Name**     | **Type**  | **Required**  | **Description**               |
| ----------- | -------------------- | ------------------------- | ------------------------- |
| code | int | Yes | Return code. ``0`` indicates successful update, non-``0`` indicates update failure. For more information, see [Error Codes](error-code-rest-api).  |
| message | String | Yes | Return error message. |
| function | UpdateFunctionResult | Yes | Update result. |

### UpdateFunctionResult Introduction

| **Name**     | **Type**  | **Required**  | **Description**               |
| ----------- | -------------------- | ------------------------- | ------------------------- |
| id | int | Yes | Function ID.  |
| functionVersionUrn | String | Yes | Function version URN, used for invoking the function. |
| revisionId | String| Yes | Function revisionId, used for publishing the function. |

## Status Codes

| **Status Code** | **Description** |
|-----|----------|
| 200 | Request successful (ok). |
| 500 | Internal Server Error. |

## Request Example

PUT {[meta service endpoint](api-meta-service-endpoint)}/serverless/v1/functions/{name}

```json
{
    "revisionId": "20250318064354416",
    "description": "this is a function",
    "handler": "handler.my_handler",
    "kind": "faas",
    "cpu": 600,
    "memory": 512,
    "timeout": 600,
    "customResources": {},
    "environment": {},
    "extendedHandler": {
        "initializer": "handler.init",
        "pre_stop": "test.prestop"
    },
    "extendedTimeout": {
        "initializer": 600,
        "pre_stop": 10
    },
    "minInstance": "0",
    "maxInstance": "10",
    "concurrentNum": "2",
    "storageType": "local",
    "codePath": "/home/sn/function-packages",
    "s3CodePath": {
    },
    "resourceAffinitySelectors": [
          {
            "group": "rg1",
            "priority": 1
        },
         {
            "group": "rg2",
            "priority": 2
        }
    ]
}
```

## Response Example

### Successful Response

```json
{
    "code": 0,
    "message": "SUCCESS",
    "function": {
        "id": "sn:cn:yrk:default:function:0@faaspy@hello2:latest",
        "createTime": "",
        "updateTime": "",
        "functionUrn": "",
        "name": "",
        "tenantId": "",
        "businessId": "",
        "productId": "",
        "reversedConcurrency": 0,
        "description": "",
        "tag": null,
        "functionVersionUrn": "sn:cn:yrk:default:function:0@faaspy@hello2:latest",
        "revisionId": "20240302084750473",
        "codeSize": 0,
        "codeSha256": "",
        "bucketId": "",
        "objectId": "",
        "handler": "",
        "layers": null,
        "cpu": 0,
        "memory": 0,
        "runtime": "",
        "timeout": 0,
        "versionNumber": "",
        "versionDesc": "",
        "environment": null,
        "customResources": null,
        "statefulFlag": 0,
        "lastModified": "",
        "Published": "",
        "minInstance": 0,
        "maxInstance": 0,
        "concurrentNum": 0,
        "funcLayer": null,
        "status": "",
        "instanceNum": 0,
        "device": {},
        "created": ""
    }
}
```

### Error Response

```json
{
    "code": 4134,
    "message": "revisionID is not the same"
}
```
