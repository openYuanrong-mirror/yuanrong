# 多语言函数编程 FAQ

## 一、无状态函数、有状态函数问题

### Driver 中正确配置了 http_proxy/https_proxy 代理地址，但  `yr.init` 接口连接 openYuanrong 集群失败，报错：“ValueError: failed to init, code: 4002, module code 20, msg: failed to connect to all addresses”

原因：openYuanrong 默认不生效 http_proxy/https_proxy 代理配置。

解决方法：配置如下环境变量，生效 http_proxy/https_proxy 代理配置。

  ```shell
  export https_proxy=http://127.0.0.1:7890   # HTTPS client 使用
  export http_proxy=http://127.0.0.1:7890    # HTTP client 使用（可与上相同）
  export YR_ENABLE_HTTP_PROXY=true
  ```

说明：与 curl 一致——HTTPS 优先读 `https_proxy`，HTTP 优先读 `http_proxy`；未设置时会 fallback 到另一个。代理 URL 支持账号密码，格式：`http://user:pass@host:port`。
