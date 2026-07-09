# KV Cache

openYuanrong provides near-computation KV caching capabilities, implementing copy-free KV data read and write based on shared memory, achieving high-performance data caching while providing data reliability through integration with external components.

## Usage Scenarios

openYuanrong KV interfaces use near-computation shared memory implementation, so data read and write latency is lower, especially noticeable for data larger than MB level. Therefore, in scenarios where large blocks of data need to be shared and passed between functions, using KV interfaces can achieve better results.

## Usage Limitations

- Keys support uppercase letters, lowercase letters, numbers, and the following characters: `~.-/_!@#%^&*()+=:;`.
- Keys cannot be empty and support a maximum length of 255 bytes.
- The maximum length of values has no limit except for Java language, but cannot exceed the shared memory size configured for the openYuanrong data system. For Java language, the maximum value length cannot exceed `Integer.MAX_VALUE - 8`.
- Data not written to secondary cache does not guarantee data reliability. Data may be lost when failures occur.

## Interface Introduction

KV interfaces support passing binary data and also support passing user-defined objects, with openYuanrong automatically handling serialization/deserialization. When writing data, the following parameters can be set:

- `writeMode`: Used to set data reliability, specifying whether data is written to secondary cache, including the following options.
   - `NONE_L2_CACHE`: Data is not written to secondary cache, does not guarantee reliability, optimal performance. When data system storage space is insufficient, one copy of data is retained.
   - `WRITE_THROUGH_L2_CACHE`: Data is synchronously written to secondary cache, highest reliability but poorest performance, performance limited by secondary cache performance.
   - `WRITE_BACK_L2_CACHE`: Data is asynchronously written to secondary cache, ensuring data reliability while performance does not significantly degrade. If openYuanrong data system components fail before data is asynchronously written to secondary cache, data loss may occur.
   - `NONE_L2_CACHE_EVICT`: Data is not written to secondary cache, does not guarantee reliability. When data system space is insufficient, old data is automatically deleted according to LRU algorithm.
- `existence`: Used to specify whether keys allow repeated writing.
- `ttlSecond`: Used to specify the data lifecycle, automatically deleting when TTL is exceeded. When configured as 0, data remains valid long-term and the system will not automatically delete it.

The APIs supported by openYuanrong KV interfaces for each language are shown in the following table.

| API Type | Python | Java | C++ |
| --------- | ---------------- | ------------- | -----------|
| Write | [yr.kv_write](../../api/distributed_programming/Python/yr.kv_write.rst): Write binary data | [YR.kv().set](../../api/distributed_programming/Java/kv.set.md): Write binary data | [YR::KV().Set](../../api/distributed_programming/Cpp/KV-Set.md): Write binary data<br>  [YR::KV().Write](../../api/distributed_programming/Cpp/KV-Write.md): Write user-defined format data, openYuanrong automatically serializes<br>  [YR::KV().MSetTx](../../api/distributed_programming/Cpp/KV-MSetTx.md): Deprecated and retained only for compatibility.<br>  [YR::KV().MWriteTx](../../api/distributed_programming/Cpp/KV-MWriteTx.md): Batch write multiple user-defined format data, openYuanrong automatically executes serialization. Multiple data have transactional semantics, guaranteeing simultaneous success or simultaneous failure.<br> |
| Read | [yr.kv_read](../../api/distributed_programming/Python/yr.kv_read.rst): Read binary data | [YR.kv().get](../../api/distributed_programming/Java/kv.get.md): Read binary data | [YR::KV().Get](../../api/distributed_programming/Cpp/KV-Get.md): Read data, returns binary data. <br> [YR::KV().Read](../../api/distributed_programming/Cpp/KV-Read.md): Read data, automatically deserializes returned data to user-defined structure. This interface can directly deserialize shared memory from the data system to user-defined structures, with one less memory copy compared to YR::KV().Get interface, providing better performance. <br> |
| Delete | [yr.kv_del](../../api/distributed_programming/Python/yr.kv_del.rst) | [YR.kv().del](../../api/distributed_programming/Java/kv.del.md)  | [YR::KV().Del](../../api/distributed_programming/Cpp/KV-Del.md) |

The timeout for KV interfaces is specified by the environment variable **DS_CONNECT_TIMEOUT_SEC**, with a default value of 1800 seconds.

## Data Consistency

openYuanrong's KV interfaces support Causal level data read-write consistency. For consistency model definitions, see [Consistency Models](https://jepsen.io/consistency/models){target="_blank"}.

## Data Spilling to Disk

KV data is stored in the shared memory of the openYuanrong data system. When memory is insufficient, it supports automatically spilling data to disk and deleting data from memory. When data needs to be read, it is automatically loaded from disk to shared memory. When disk space is also insufficient, if data has been written to secondary cache, it is automatically deleted from local disk and memory. When data needs to be read, it is automatically loaded from secondary cache to shared memory.

The configuration for KV data spilling to disk is the same as for data objects, see the description in [Data Objects](./index.md).

## Data Reliability

openYuanrong KV interfaces provide reliability semantics, configuring data reliability levels through the `writeMode` parameter in data write interfaces. The data system achieves data reliability by integrating with external storage components as secondary cache. You need to configure secondary cache related parameters when deploying openYuanrong. Currently supported secondary cache components are: OBS/SFS.

Note that if secondary cache is not configured during deployment, using data write interfaces with `writeMode` parameter configured as `WRITE_THROUGH_L2_CACHE` or `WRITE_BACK_L2_CACHE` will return failure.

Secondary cache parameter configuration reference when deploying openYuanrong cluster is as follows.

```yaml
# Specify the type of secondary cache. Optional values are: 'obs', 'sfs', 'none'.
# Default value is 'none', indicating secondary cache is not supported.
l2CacheType: "none"
```

Configuration parameters for integrating with various external components are as follows:

::::{tab-set}
:::{tab-item} obs

```yaml
obs:
  # The access key for obs AK/SK authentication. If the value of encryptKit is not plaintext, encryption is required.
  obsAccessKey: ""
  # The secret key for obs AK/SK authentication. If the value of encryptKit is not plaintext, encryption is required.
  obsSecretKey: ""
  # OBS endpoint. Example: "xxx.hwcloudtest.cn"
  obsEndpoint: ""
  # OBS bucket name.
  obsBucket: ""
  # Whether to enable the https in obs. false: use HTTP (default), true: use HTTPS
  obsHttpsEnabled: false
  # Use cloud service token rotation to connect obs.
  cloudServiceTokenRotation:
    # Whether to use ccms credential rotation mode to access OBS, default is false. If is enabled, need to specify
    # iamHostName, identityProvider, projectId, regionId at least.
    # In addition, obsEndpoint and obsBucket need to be specified.
    enable: false
    # Domain name of the IAM token to be obtained.
    iamHostName: ""
    # Provider that provides permissions for the ds-worker. Example: csms-datasystem.
    identityProvider: ""
    # Project id of the OBS to be accessed. Example: fb6a00ff7ae54a5fbb8ff855d0841d00.
    projectId: ""
    # Region id of the OBS to be accessed. Example: cn-north-7.
    regionId: ""
    # Whether to access OBS of other accounts by agency, default is false. If is true, need to specify tokenAgencyName
    # and tokenAgencyDomain.
    enableTokenByAgency: false
    # Agency name for proxy access to other accounts. Example: obs_access.
    tokenAgencyName: ""
    # Agency domain for proxy access to other accounts. Example: op_svc_cff.
    tokenAgencyDomain: ""
```

:::
:::{tab-item} sfs

```yaml
# The path to the mounted SFS.
sfsPath: ""
```

:::
::::
