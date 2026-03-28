# aio-yr 使用说明

`example/aio` 现在拆成两个镜像：

- `aio-yr:latest`
  - 主控制面镜像
  - 包含 web terminal、Traefik、`yr`、`runtime-launcher`、`dockerd`
- `aio-yr-runtime:latest`
  - Python 3.9 runtime rootfs 镜像
  - 只包含 Python 和 `openyuanrong_sdk`

本示例使用真实 Docker in Docker。外层只启动一个 `aio-yr` 主容器，主容器内会先启动 `dockerd`，再由 `runtime-launcher` 拉起 `aio-yr-runtime:latest` 容器。

## 准备构建产物

先在仓库根目录执行：

```bash
make all
```

这一步会：

- 编译各模块
- 产出 wheel 和二进制
- 将 AIO 需要的构建输入拷贝到 `example/aio/pkg/`

然后执行：

```bash
make image
```

`make image` 会调用 `example/aio/build-images.sh`，由脚本完成当前 AIO 镜像流程。

`build-images.sh` 不再负责打包或拷贝产物，只负责：

1. 校验 `example/aio/pkg/` 中的必需产物是否已存在
2. 构建 `Dockerfile.runtime`
3. 导出 runtime tar
4. 构建 `Dockerfile.aio-yr`

## 手动构建

如果你要手工执行底层脚本：

```bash
make all
example/aio/build-images.sh
```

## 启动 aio-yr

推荐顺序：

```bash
make all && make image && bash example/aio/run.sh
```

`run.sh` 只负责启动，不负责构建。脚本会删除已有 `aio-yr` 容器，并以 `--privileged --cgroupns=host` 启动新的 `aio-yr:latest`。

也支持环境变量覆盖：

```bash
AIO_CONTAINER_NAME=my-aio AIO_PORT=9443 bash example/aio/run.sh
```

旧的 [`Dockerfile`](/home/wyc/code/sandbox/example/aio/Dockerfile) 保留为兼容入口，内容与 `Dockerfile.aio-yr` 一致；推荐显式使用 `Dockerfile.aio-yr` 和 `Dockerfile.runtime`。

启动后访问：

```text
https://127.0.0.1:38888/
https://127.0.0.1:38888/terminal
```

## 宿主机用 SDK 创建 sandbox

如果要绕过 frontend 的 job 提交链，直接在宿主机用 SDK 创建 sandbox，先确保：

- `aio-yr` 已启动
- 宿主机有 conda 环境 `yr`
- 该环境使用 Python 3.9

然后执行：

```bash
example/aio/create-sandbox-host.sh
```

也可以显式传名字和 namespace：

```bash
example/aio/create-sandbox-host.sh my-sandbox sandbox
```

这个脚本会：

1. 把 `output/openyuanrong_sdk-*.whl` 安装到宿主 conda `yr` 环境
2. 用 `server_address=127.0.0.1:38888`
3. 显式设置 `in_cluster=false`
4. 通过 SDK 调用 `yr.sandbox.SandBox()` 创建实例

## 宿主机验证端口转发

如果要直接验证 Traefik 端口转发链路，可以执行：

```bash
example/aio/verify-port-forward-host.sh
```

这个脚本会：

1. 在宿主 conda `yr` 环境安装当前 `openyuanrong_sdk` wheel
2. 用 `in_cluster=false` 创建一个 `detached` sandbox
3. 为 sandbox 配置 `port_forwardings=[8080]`
4. 在 sandbox 内启动 `python3 -m http.server 8080`
5. 从宿主访问 `https://127.0.0.1:38888/<instance_id>/8080`
6. 验证完成后自动销毁实例

## 运行方式说明

- `supervisord-entrypoint.sh` 先启动容器内 `dockerd`
- 如果内层 daemon 还没有 `aio-yr-runtime:latest`，会自动从 `/opt/runtime-images/aio-yr-runtime.tar` 执行 `docker load`
- 然后再启动 Traefik、`runtime-launcher` 和 Yuanrong master
- [`services.yaml`](/home/wyc/code/sandbox/example/aio/services.yaml) 中 `py39` runtime 会使用 `aio-yr-runtime:latest`

## 当前范围

这轮只保留 AIO 控制面和 Python runtime：

- 保留 web terminal、Traefik、Yuanrong master
- 使用真实 dind，不再依赖宿主 Docker socket 挂载
- 暂时不内置 `claude-code`
- 暂时不内置 `openclaw`

## 后续扩展

低优先级规划项：

- `aio-yr` 支持 1 到 3 个 master 容器
- 支持 N 个 slave 容器组建集群
