本目录存放 `example/traefik` 的本地开发证书。

- `wyc.pc.crt` 和 `wyc.pc.key` 为仓库内置自签名证书，供 Traefik 在 `https://wyc.pc:18888` 上使用。
- 证书 SAN 包含 `wyc.pc`、`localhost` 和 `127.0.0.1`。
- 这是开发用途证书，不应用于生产环境。
