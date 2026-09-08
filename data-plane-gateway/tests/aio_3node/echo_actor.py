#!/usr/bin/env python3
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import base64
import configparser
import json
import logging
import sys
import time

import yr
from yr.sandbox.sandbox import SandboxInstance


# Keep machine-readable results on stdout without diagnostic prefixes.
result_logger = logging.getLogger(__name__ + ".result")
result_logger.setLevel(logging.INFO)
result_logger.propagate = False
result_handler = logging.StreamHandler(sys.stdout)
result_handler.setFormatter(logging.Formatter("%(message)s"))
result_logger.addHandler(result_handler)


SERVER_SOURCE = r'''#!/usr/bin/env python3
import json
import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = json.dumps(
            {
                "hostname": socket.gethostname(),
                "path": self.path,
                "runtime_id": os.getenv("RUNTIME_ID", ""),
            },
            sort_keys=True,
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        return


ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1])), Handler).serve_forever()
'''


def create_sandbox(node_tag, port):
    options = yr.InvokeOptions()
    options.custom_resources[node_tag] = 1
    options.skip_serialize = True
    options.idle_timeout = 900
    options.custom_extensions["rootfs"] = json.dumps(
        {"type": "image", "imageurl": "aio-yr-runtime:latest"}
    )
    sandbox = SandboxInstance.options(options).invoke(None, None)
    instance_id = sandbox.real_id
    # This method call waits until the pre-deployed SDK class in the isolated
    # rootfs is initialized before installing the test server.
    yr.get(sandbox.get_name.invoke())
    encoded_server = base64.b64encode(SERVER_SOURCE.encode()).decode()
    write_result = yr.get(
        sandbox.execute.invoke(
            "python3 -c \"import base64; "
            "open('/tmp/yr_gateway_echo.py','wb').write("
            f"base64.b64decode('{encoded_server}'))\""
        )
    )
    if write_result.get("returncode") != 0:
        raise RuntimeError(f"failed to install sandbox HTTP server: {write_result}")
    result = yr.get(
        sandbox.execute.invoke(
            f"nohup python3 /tmp/yr_gateway_echo.py {port} "
            ">/tmp/yr_gateway_echo.log 2>&1 </dev/null &"
        )
    )
    if result.get("returncode") != 0:
        raise RuntimeError(f"failed to start sandbox HTTP server: {result}")
    hostname_result = yr.get(sandbox.execute.invoke("hostname"))
    if hostname_result.get("returncode") != 0:
        raise RuntimeError(f"failed to read sandbox hostname: {hostname_result}")
    return sandbox, {
        "hostname": hostname_result["stdout"].strip(),
        "instance_id": instance_id,
        "node_tag": node_tag,
        "port": port,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/tmp/yr-gateway-actors.json")
    parser.add_argument("--hold-seconds", type=int, default=900)
    args = parser.parse_args()

    ini = configparser.ConfigParser()
    ini.read("/root/.yr/config.ini")
    settings = ini["python"]
    yr.init(
        yr.Config(
            server_address=settings["server_address"],
            ds_address=settings["datasystem_address"],
            in_cluster=settings.get("in_cluster", "true").strip().lower() == "true",
            master_addr_list=[settings["master_addr"]],
        )
    )
    sandboxes = []
    results = []
    try:
        for tag, port in (("node_tag2", 18080), ("node_tag3", 18081)):
            sandbox, details = create_sandbox(tag, port)
            sandboxes.append(sandbox)
            results.append(details)
        with open(args.output, "w", encoding="utf-8") as stream:
            json.dump(results, stream, sort_keys=True)
        result_logger.info("%s", json.dumps(results, sort_keys=True))
        time.sleep(args.hold_seconds)
    finally:
        for sandbox in sandboxes:
            try:
                sandbox.terminate()
            except Exception:
                logging.exception("Failed to terminate sandbox during actor cleanup")
        yr.finalize()


if __name__ == "__main__":
    main()
