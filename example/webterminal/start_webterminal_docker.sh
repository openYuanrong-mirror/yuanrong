docker run -d \
  --name webterminal \
  --restart unless-stopped \
  --privileged \
  -p 8888:8888 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /home/wyc:/ws \
  -v /usr/bin/docker:/usr/bin/docker \
  swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev/compile_x86:2.1 \
  bash -c "while true;do sleep 300;done"
