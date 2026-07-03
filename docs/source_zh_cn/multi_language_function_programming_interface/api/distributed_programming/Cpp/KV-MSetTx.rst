KV().MSetTx
============

.. warning::

    ``KV().MSetTx`` 已废弃，仅为兼容历史版本保留。新代码请勿继续使用该接口。

``KV().MSetTx`` 曾用于批量存储二进制数据到数据系统，类似 Redis 的 Mset 接口。

.. cpp:function:: static inline void YR::KVManager::MSetTx(const std::vector<std::string> &keys, const std::vector<char*> &vals, const std::vector<size_t> &lens, ExistenceOpt existence)

    已废弃，仅为兼容历史版本保留。新代码请勿继续使用该接口。

    .. note::
        支持最大每秒 250 次请求。

    参数：
        - **keys** - 用于标识数据的键列表。列表不能为空，最大长度为 ``8``。
        - **vals** - 需要存储的二进制数据列表。每条数据都和 ``keys`` 中的键一一对应，且列表长度和 ``keys`` 列表长度相同。
        - **lens** - ``vals`` 中每条数据的长度列表。和 ``vals`` 列表中的数据一一对应，且列表长度和 ``keys`` 列表长度相同。
        - **existence** - 是否允许键重复写入。必须设置为 ``YR::ExistenceOpt::NX``，表示不允许。

    抛出：
        :cpp:class:`Exception` -

        - 1001：参数错误。提供详细的错误信息。
        - 4206：键已存在。当参数 `existence` 设置为 ``YR::ExistenceOpt::NX`` 且该键已被使用时触发。
        - 包含错误信息的其他异常。

.. cpp:function:: static inline void YR::KVManager::MSetTx(const std::vector<std::string> &keys, const std::vector<std::string> &vals, ExistenceOpt existence)

    已废弃，仅为兼容历史版本保留。新代码请勿继续使用该接口。

    .. note::
        支持最大每秒 250 次请求。

    参数：
        - **keys** - 用于标识数据的键列表。列表不能为空，最大长度为 ``8``。
        - **vals** - 需要存储的字符串列表。每条字符串都和 ``keys`` 中的键一一对应，且列表长度和 ``keys`` 列表长度相同。
        - **existence** - 是否允许键重复写入。必须设置为 ``YR::ExistenceOpt::NX``，表示不允许。

    抛出：
        :cpp:class:`Exception` -

        - 1001：参数错误。提供详细的错误信息。
        - 4206：键已存在。当参数 `existence` 设置为 ``YR::ExistenceOpt::NX`` 且该键已被使用时触发。
        - 包含错误信息的其他异常。

.. cpp:function:: static inline void YR::KVManager::MSetTx(const std::vector<std::string> &keys, const std::vector<char*> &vals, const std::vector<size_t> &lens, const MSetParam &mSetParam)

    已废弃，仅为兼容历史版本保留。新代码请勿继续使用该接口。

    .. note::
        支持最大每秒 250 次请求。

    参数：
        - **keys** - 用于标识数据的键列表。列表不能为空，最大长度为 ``8``。
        - **vals** - 需要存储的二进制数据列表。每条数据都和 ``keys`` 中的键一一对应，且列表长度和 ``keys`` 列表长度相同。
        - **lens** - ``vals`` 中每条数据的长度列表。和 ``vals`` 列表中的数据一一对应，且列表长度和 ``keys`` 列表长度相同。
        - **mSetParam** - 设置数据的可靠性级别等属性。

    抛出：
        :cpp:class:`Exception` -

        - 1001：参数错误。提供详细的错误信息。
        - 4206：键已存在。当参数 `existence` 设置为 ``YR::ExistenceOpt::NX`` 且该键已被使用时触发。
        - 包含错误信息的其他异常。

.. cpp:function:: static inline void YR::KVManager::MSetTx(const std::vector<std::string> &keys, const std::vector<std::string> &vals, const MSetParam &mSetParam)

    已废弃，仅为兼容历史版本保留。新代码请勿继续使用该接口。

    .. note::
        支持最大每秒 250 次请求。

    参数：
        - **keys** - 用于标识数据的键列表。列表不能为空，最大长度为 ``8``。
        - **vals** - 需要存储的字符串列表。每条字符串都和 ``keys`` 中的键一一对应，且列表长度和 ``keys`` 列表长度相同。
        - **mSetParam** - 设置数据的可靠性级别等属性。

    抛出：
        :cpp:class:`Exception` -

        - 1001：参数错误。提供详细的错误信息。
        - 4206：键已存在。当参数 `existence` 设置为 ``YR::ExistenceOpt::NX`` 且该键已被使用时触发。
        - 包含错误信息的其他异常。

参数结构补充说明如下：

.. cpp:struct:: MSetParam

    用于配置数据的可靠性等属性。

    **公共成员**

    .. cpp:member:: WriteMode writeMode = WriteMode::NONE_L2_CACHE

        写入模式

        设置数据的可靠性。服务端配置支持二级缓存比如 redis 服务时，使用该配置可以保证数据可靠性。默认值为 :cpp:enumerator:`YR::WriteMode::NONE_L2_CACHE`。
    
    .. cpp:member:: uint32_t ttlSecond = 0
        
        生存时间（TTL），单位为秒。

        指定数据在删除前保留的时间。默认值为 ``0``，表示该键将一直存在，直到使用 ``Del`` 接口显式删除。

    .. cpp:member:: ExistenceOpt existence = ExistenceOpt::NX

        是否存在选项。

        用于表示是否允许键重复写入键。默认值 ``YR::ExistenceOpt::NX`` 表示不允许，可选值 ``YR::ExistenceOpt::NONE`` 表示允许。

    .. cpp:member:: CacheType cacheType = CacheType::MEMORY

        缓存介质类型。

        指定数据缓存介质。默认值 ``YR::CacheType::Memory`` 表示缓存到内存，可选值 ``YR::CacheType::Disk`` 表示缓存到磁盘。

    .. cpp:member:: std::unordered_map<std::string, std::string> extendParams

        扩展参数。

        配置其他扩展参数。
