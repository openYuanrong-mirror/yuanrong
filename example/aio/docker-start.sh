docker run -d \
  --name openyuanrong \
  --restart unless-stopped \
  -p 18888:8888 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  swr.cn-southwest-2.myhuaweicloud.com/openyuanrong/openyuanrongaio:v0.2
