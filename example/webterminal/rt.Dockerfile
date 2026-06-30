FROM swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev/compile_x86:2.1

COPY openyuanrong_sdk-0.7.0.dev0-cp39-cp39-linux_x86_64.whl /tmp/
RUN pip3.9 install /tmp/openyuanrong_sdk-0.7.0.dev0-cp39-cp39-linux_x86_64.whl && rm /tmp/openyuanrong_sdk-0.7.0.dev0-cp39-cp39-linux_x86_64.whl


