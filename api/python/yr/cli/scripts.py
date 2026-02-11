#!/usr/bin/env python3
# coding=UTF-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
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

import asyncio
from datetime import datetime
import os
import uuid
import shutil
import sys
import subprocess
import click
import json
import logging
import requests
from requests.exceptions import RequestException
from typing import Any, Dict, Optional

import yr
from yr.cli.exec import run_client


__server_address = None
__ds_address = None
__metaservice_address = None
__client_cert = None
__client_key = None
__ca_cert = None
__server_name = None
__user = None


class FunctionName:
    """Function name components"""

    def __init__(self, raw_name: str, version: str = "latest"):
        self.raw_name = raw_name
        self.type = "0"
        self.service = None
        self.name = None
        self.version = version
        self.parse()

    def __str__(self):
        return f"{self.service}@{self.name}:{self.version}"

    def parse(self):
        """Parse function name into components"""
        name_part = self.raw_name
        if ":" in self.raw_name:
            name_part, version_part = self.raw_name.split(":", 1)
            self.version = version_part
        if "@" in name_part:
            parts = name_part.split("@")
            if len(parts) == 3:
                self.type = parts[0]
                self.service = parts[1]
                self.name = parts[2]
            elif len(parts) == 2:
                self.service = parts[0]
                self.name = parts[1]
            else:
                raise ValueError(f"Invalid function name format: {self.raw_name}")

    def full_name(self):
        """Get full function name"""
        return f"{self.type}@{self.service}@{self.name}:{self.version}"

    def full_name_no_version(self):
        """Get full function name without version"""
        return f"{self.type}@{self.service}@{self.name}"


class HTTPClient:
    """HTTP client with mutual TLS authentication support"""

    def __init__(
        self,
        timeout: int = 30,
        client_cert: Optional[str] = None,
        client_key: Optional[str] = None,
        ca_cert: Optional[str] = None,
        verify: bool = False,
        server_name: Optional[str] = None,
    ):
        self.timeout = timeout
        self.session = requests.Session()
        self.client_cert = client_cert
        self.client_key = client_key
        self.ca_cert = ca_cert
        self.verify = verify
        self.server_name = server_name

    def request(
        self,
        url: str,
        data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        method: str = "POST",
    ) -> Dict[str, Any]:
        """
        Send POST JSON request

        Args:
            url: Target URL
            data: JSON data
            headers: Request headers

        Returns:
            Response data
        """

        default_headers = {
            "Content-Type": "application/json",
            "User-Agent": "DeploymentScript/1.0",
        }
        if headers:
            default_headers.update(headers)

        logging.debug(f"{method.lower()} to {url}")
        logging.debug(f"headers: {json.dumps(default_headers, indent=2)}")
        logging.debug(f"body: {json.dumps(data, indent=2, ensure_ascii=False)}")

        # Configure certificates
        cert = None
        if self.client_cert and self.client_key:
            cert = (self.client_cert, self.client_key)
        elif self.client_cert:
            cert = self.client_cert

        verify = self.ca_cert if self.ca_cert else self.verify
        if url.startswith("http://") and verify:
            url = url.replace("http://", "https://", 1)

        # If server_name is specified, use hostname overwrite
        if self.server_name:
            from requests.adapters import HTTPAdapter
            from urllib3.poolmanager import PoolManager
            from urllib3.util.ssl_ import create_urllib3_context
            import ssl

            class HostNameOverridePoolManager(PoolManager):
                def __init__(self, *args, server_hostname=None, **kwargs):
                    self.server_hostname = server_hostname
                    super().__init__(*args, **kwargs)

                def _new_pool(self, scheme, host, port, request_context=None):
                    # Inject assert_hostname when creating connection pool
                    if request_context is None:
                        request_context = self.connection_pool_kw.copy()
                    if self.server_hostname:
                        request_context["assert_hostname"] = self.server_hostname
                    return super()._new_pool(scheme, host, port, request_context)

            class HostNameOverrideAdapter(HTTPAdapter):
                def __init__(self, server_hostname, *args, **kwargs):
                    self.server_hostname = server_hostname
                    super().__init__(*args, **kwargs)

                def init_poolmanager(
                    self, connections, maxsize, block=False, **pool_kwargs
                ):
                    # Use custom PoolManager
                    self.poolmanager = HostNameOverridePoolManager(
                        num_pools=connections,
                        maxsize=maxsize,
                        block=block,
                        server_hostname=self.server_hostname,
                        **pool_kwargs,
                    )

            # Create temporary session for this request
            temp_session = requests.Session()
            adapter = HostNameOverrideAdapter(self.server_name)
            temp_session.mount("https://", adapter)

            response = temp_session.request(
                method.upper(),
                url,
                json=data,
                headers=default_headers,
                timeout=self.timeout,
                cert=cert,
                verify=verify,
            )
        else:
            response = self.session.request(
                method.upper(),
                url,
                json=data,
                headers=default_headers,
                timeout=self.timeout,
                cert=cert,
                verify=verify,
            )

        try:
            result = response.json() if response.content else {}

            logging.debug(f"response status: {response.status_code}")
            logging.debug(
                f"response data: {json.dumps(result, indent=2, ensure_ascii=False)}"
            )

            return {
                "success": response.status_code == 200,
                "error": result,
                "status_code": response.status_code,
                "data": result,
                "headers": dict(response.headers),
            }

        except RequestException as e:
            logging.debug(f"HTTP failed: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "status_code": (
                    getattr(e.response, "status_code", None)
                    if hasattr(e, "response")
                    else None
                ),
            }


class YRContext:
    def __init__(self, server_address, ds_address, user=None):
        self.__server_address = server_address
        self.__ds_address = ds_address
        self.__user = user

    def __enter__(self):
        cfg = yr.Config()
        cfg.log_dir = "/tmp/yr_sessions/driver"
        if self.__user:
            cfg.tenant_id = self.__user
        if self.__server_address and self.__ds_address:
            cfg.server_address = self.__server_address
            cfg.ds_address = self.__ds_address
            return yr.init(cfg)
        if self.__server_address:
            cfg.server_address = self.__server_address
            cfg.in_cluster = False
            return yr.init(cfg)
        return yr.init(cfg)

    def __exit__(self, exc_type, exc_value, exc_traceback):
        yr.finalize()
        return False


def get_name_from_info(function_info):
    name = function_info.get("name")
    version = function_info.get("versionNumber")
    return FunctionName(name, version)


def deploy_function(function_json, user):
    http_client = HTTPClient(
        timeout=30,
        client_cert=__client_cert,
        client_key=__client_key,
        ca_cert=__ca_cert,
        server_name=__server_name,
    )
    url = f"http://{__metaservice_address}/serverless/v1/functions"
    headler = {}
    if user:
        headler = {"X-Tenant-Id": user}
    resp = http_client.request(url, function_json, headers=headler, method="POST")
    if resp["success"]:
        return True, resp["data"]["function"]
    else:
        return False, resp


def update_function(function_json, user):
    name = function_json.get("name")
    if not name:
        raise RuntimeError("function name is required to update function.")
    http_client = HTTPClient(
        timeout=30,
        client_cert=__client_cert,
        client_key=__client_key,
        ca_cert=__ca_cert,
        server_name=__server_name,
    )
    url = f"http://{__metaservice_address}/serverless/v1/functions/{name}"
    headler = {}
    if user:
        headler = {"X-Tenant-Id": user}
    resp = http_client.request(url, function_json, headers=headler, method="PUT")
    if resp["success"]:
        return True, resp["data"]["result"]
    else:
        return False, resp


def delete_function(function_name, user):
    http_client = HTTPClient(
        timeout=30,
        client_cert=__client_cert,
        client_key=__client_key,
        ca_cert=__ca_cert,
        server_name=__server_name,
    )
    url = f"http://{__metaservice_address}/serverless/v1/functions/{function_name.full_name_no_version()}?versionNumber={function_name.version}"
    headler = {}
    if user:
        headler = {"X-Tenant-Id": user}
    resp = http_client.request(url, {}, headers=headler, method="DELETE")
    if resp["success"]:
        return True, None
    else:
        return False, resp


def query_function(function_name, user=None):
    http_client = HTTPClient(
        timeout=30,
        client_cert=__client_cert,
        client_key=__client_key,
        ca_cert=__ca_cert,
        server_name=__server_name,
    )
    if function_name is None:
        url = f"http://{__metaservice_address}/serverless/v1/functions"
    else:
        url = f"http://{__metaservice_address}/serverless/v1/functions/{function_name.full_name_no_version()}?versionNumber={function_name.version}"
    headler = {}
    if user:
        headler = {"X-Tenant-Id": user}
    resp = http_client.request(url, {}, headers=headler, method="GET")
    if resp["success"]:
        if function_name is None:
            return True, resp["data"]["result"]["functions"]
        else:
            return True, resp["data"]["function"]
    else:
        return False, resp


def publish_function(function_name, publish_json, user=None):
    http_client = HTTPClient(
        timeout=30,
        client_cert=__client_cert,
        client_key=__client_key,
        ca_cert=__ca_cert,
        server_name=__server_name,
    )
    url = f"http://{__metaservice_address}/serverless/v1/functions/{function_name.full_name_no_version()}/versions"
    headler = {}
    if user:
        headler = {"X-Tenant-Id": user}
    resp = http_client.request(url, publish_json, headers=headler, method="POST")
    if resp["success"]:
        return True, resp["data"]["function"]
    else:
        return False, resp


def install_requirements(requirements_file, target_dir):
    """
    Install Python dependencies from requirements file to target directory.

    Args:
        requirements_file: Path to requirements.txt file
        target_dir: Target directory to install dependencies

    Returns:
        True if successful, False otherwise
    """
    if not os.path.exists(requirements_file):
        print(f"Requirements file not found: {requirements_file}")
        return False

    print(f"Installing dependencies from {requirements_file} to {target_dir}...")

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                requirements_file,
                "-t",
                target_dir,
                "--no-warn-script-location",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"Failed to install dependencies: {result.stderr}")
            return False

        print(f"Successfully installed dependencies to {target_dir}")
        return True

    except Exception as e:
        print(f"Error installing dependencies: {str(e)}")
        return False


def package(backend, code_path, format):
    real_code_path = os.path.realpath(code_path)
    file_name = f"code-{uuid.uuid4().hex}"
    archive_file = os.path.join("/tmp", file_name)
    if format == "zip":
        shutil.make_archive(archive_file, format, real_code_path)
    elif format == "img":
        result = subprocess.run(
            [
                "mkfs.erofs",
                "-E",
                "noinline_data",
                f"{archive_file}.{format}",
                real_code_path,
            ]
        )
        if result.returncode != 0:
            sys.exit(result.returncode)
    else:
        print(f"unkown format: {format}")
        sys.exit(1)
    if backend == "ds":
        with YRContext(__server_address, __ds_address):
            with open(f"{archive_file}.{format}", "rb") as f:
                yr.kv_write(file_name, f.read())

        package_key = f"ds://{file_name}.{format}"
    else:
        print("not support backend: %s" % backend)
        sys.exit(1)
    return real_code_path, package_key


def invoke_function(function_name, payload, headers=None, user=None, timeout=30):
    if headers is None:
        headers = {}
    http_client = HTTPClient(
        timeout=timeout,
        client_cert=__client_cert,
        client_key=__client_key,
        ca_cert=__ca_cert,
        server_name=__server_name,
    )
    url = f"http://{__server_address}/{user}/{str(function_name).replace('@', '/')}"
    resp = http_client.request(url, payload, headers=headers, method="POST")
    if resp["success"]:
        return True, resp["data"]
    else:
        return False, resp


@click.group()
@click.option(
    "--server-address",
    required=False,
    type=str,
    envvar="YR_SERVER_ADDRESS",
    help="YuanRong Server address",
)
@click.option(
    "--ds-address",
    required=False,
    type=str,
    envvar="YR_DS_ADDRESS",
    help="YuanRong DataSystem address",
)
@click.option(
    "--metaservice-address", required=False, type=str, envvar="YR_METASERVICE_ADDRESS"
)
@click.option(
    "--client-cert",
    required=False,
    type=str,
    envvar="YR_CERT_FILE",
    help="Client certificate file path",
)
@click.option(
    "--client-key",
    required=False,
    type=str,
    envvar="YR_PRIVATE_KEY_FILE",
    help="Client private key file path",
)
@click.option(
    "--ca-cert",
    required=False,
    type=str,
    envvar="YR_VERIFY_FILE",
    help="CA certificate file path",
)
@click.option(
    "--server-name",
    required=False,
    type=str,
    envvar="YR_SERVER_NAME",
    help="Server name for certificate verification (SNI)",
)
@click.option("--log-level", required=False, type=str, default="INFO")
@click.option("--user", required=False, type=str, default="default")
@click.version_option(package_name="openyuanrong-sdk")
def cli(
    server_address,
    ds_address,
    metaservice_address,
    client_cert,
    client_key,
    ca_cert,
    server_name,
    log_level,
    user,
):
    """
    run command
    """
    if server_address:
        global __server_address
        __server_address = server_address
    if ds_address:
        global __ds_address
        __ds_address = ds_address
    if metaservice_address:
        global __metaservice_address
        __metaservice_address = metaservice_address
    if client_cert:
        global __client_cert
        __client_cert = client_cert
    if client_key:
        global __client_key
        __client_key = client_key
    if ca_cert:
        global __ca_cert
        __ca_cert = ca_cert
    if server_name:
        global __server_name
        __server_name = server_name
    if user:
        global __user
        __user = user
    logging.basicConfig(level=getattr(logging, log_level.upper(), None))


@cli.command()
@click.option("--backend", required=False, type=str, default="ds")
@click.option("--code-path", required=False, type=str, default=".")
@click.option("--format", required=False, type=str, default="zip")
@click.option("--function-json", required=False, type=str, default=None)
@click.option("--skip-package", required=False, type=bool, default=False)
@click.option("--update", required=False, is_flag=True, default=False)
@click.option(
    "-r",
    "--requirements",
    required=False,
    type=str,
    default=None,
    help="Path to requirements.txt file for installing dependencies",
)
def deploy(
    backend, code_path, format, function_json, skip_package, update, requirements
):
    if function_json:
        with open(function_json, "r") as f:
            function_json = json.load(f)
    # Install dependencies if requirements file is provided
    if requirements and not skip_package:
        real_code_path = os.path.realpath(code_path)
        if not install_requirements(requirements, real_code_path):
            print("Failed to install dependencies. Deployment aborted.")
            sys.exit(1)
    if not skip_package:
        real_code_path, package_key = package(backend, code_path, format)
        if function_json:
            function_json["storageType"] = "working_dir"
            function_json["codePath"] = package_key
        else:
            print(
                f"""already upload {real_code_path} to {backend}.
export YR_WORKING_DIR={package_key} to set this package.
yrcli clear {package_key} to delete this package.
yrcli download {package_key} to download this package."""
            )
            return
    if function_json:
        name = function_json.get("name")
        if name is None:
            print("function name is required to deploy function.")
            sys.exit(1)
        version = "latest" if function_json.get("kind", "faas") == "faas" else "$latest"
        name = FunctionName(name, version)
        query_ret, function_info = query_function(name, __user)
        if query_ret and not update:
            print(f"function {name} already exists, use --update to update it.")
            sys.exit(1)
        if query_ret:
            function_json["revisionId"] = function_info.get("revisionId")
            ret = update_function(function_json, __user)
            if ret[0]:
                name = get_name_from_info(ret[1])
                print(f"succeed to update function: {name}")
            else:
                print(f"failed to update function: {ret[1]['error']}")
        else:
            ret = deploy_function(function_json, __user)
            if ret[0]:
                name = get_name_from_info(ret[1])
                print(f"succeed to deploy function: {name}")
            else:
                print(f"failed to deploy function: {ret[1]}")
    else:
        print("function json is required to deploy function.")


@cli.command()
@click.option("-f", "--function-name", required=False, type=str, default=None)
@click.option("-v", "--version", required=False, type=str, default=None)
def publish(function_name, version):
    if ":" not in function_name and version is None:
        print("version is required if function name has no version.")
        sys.exit(1)
    if ":" in function_name and version is not None:
        print("version should not be specified if function name has version.")
        sys.exit(1)
    if ":" in function_name:
        version = function_name.split(":")[1]
    function_name = FunctionName(function_name, version)
    publish_json = {}
    query_ret, function_info = query_function(function_name, __user)
    if not query_ret:
        print(f"function not found: {function_name}")
        sys.exit(1)
    publish_json["revisionId"] = function_info.get("revisionId")
    publish_json["kind"] = function_info.get("kind", "faas")
    if version:
        publish_json["versionNumber"] = version
    ret = publish_function(function_name, publish_json, __user)
    if ret[0]:
        print(f"succeed to publish function: {ret[1]}")
    else:
        print(f"failed to publish function: {ret[1]}")


@cli.command()
@click.option("-f", "--function-name", required=True, type=str, default=None)
def query(function_name):
    function_name = FunctionName(function_name)
    ret, resp = query_function(function_name, __user)
    if ret:
        print(json.dumps(resp, indent=2, ensure_ascii=False))
    else:
        print(f"function not found: {function_name}")


@cli.command()
def list():
    ret, resp = query_function(None, __user)
    if ret and len(resp) > 0:
        for function in resp:
            print(f"{function['name'][2:]}:{function['versionNumber']}")
    else:
        print(f"user {__user} has no function.")


@cli.command()
@click.option("-f", "--function-name", required=True, type=str, default=None)
@click.option("--no-clear-package", is_flag=True, default=False)
@click.option("-v", "--version", required=False, type=str, default="latest")
def delete(function_name, no_clear_package, version):
    function_name = FunctionName(function_name, version)
    if not no_clear_package:
        ret, function_info = query_function(function_name, __user)
        if not ret:
            print(f"function not found.")
            return
        code_path = function_info.get("codePath")
        if code_path and code_path.startswith("ds://"):
            key = code_path.strip("ds://").split(".")[0]
            with YRContext(__server_address, __ds_address):
                yr.kv_del(key)
            print(f"succeed to del package {code_path}")
    ret, _ = delete_function(function_name, __user)
    if not ret:
        print(f"function not found.")
    else:
        print(f"succeed to delete function: {function_name}")


@cli.command
@click.argument("package", type=str)
def clear(package):
    if package.startswith("ds://"):
        key = package.strip("ds://").split(".")[0]
        with YRContext(__server_address, __ds_address):
            yr.kv_del(key)
        print(f"succeed to del {package}")


@cli.command
@click.argument("package", type=str)
def download(package):
    if package.startswith("ds://"):
        key = package.strip("ds://").split(".")[0]
        file_name = package.strip("ds://")
        with YRContext(__server_address, __ds_address):
            with open(file_name, "wb") as f:
                value = yr.kv_get(key)
                f.write(value)
        print(f"save {package} to {file_name}")


@cli.command
@click.option("-f", "--function-name", required=True, type=str, default=None)
@click.option("--payload", required=False, type=str, default=None)
@click.option("--timeout", required=False, type=int, default=30)
@click.option("--header", required=False, type=str, multiple=True)
def invoke(function_name, payload, timeout, header):
    headers = {}
    for i in range(len(header)):
        if ":" in header[i]:
            key, value = header[i].split(":", 1)
            headers[key.strip()] = value.strip()
    function_name = FunctionName(function_name)
    if payload:
        payload_dict = json.loads(payload)
    else:
        payload_dict = {}
    ret, resp = invoke_function(
        function_name, payload_dict, headers=headers, user=__user, timeout=timeout
    )
    if ret:
        print(json.dumps(resp, indent=2, ensure_ascii=False))
    else:
        print(f"failed to invoke function: {resp['error']}")


@cli.command(
    "deploy-language-rt",
    context_settings=dict(
        ignore_unknown_options=True,
        allow_extra_args=True,
        allow_interspersed_args=False,
    ),
)
@click.option(
    "--runtime",
    required=False,
    type=click.Choice(["python3.11", "python3.9", "python3.10", "python3.12"]),
    help="Runtime language version",
)
@click.option(
    "--sdk",
    is_flag=True,
    default=False,
    help="sdk language",
)
@click.option("--no-rootfs", is_flag=True, default=False, help="Deploy without rootfs")
@click.option(
    "--function-json",
    required=False,
    type=str,
    default=None,
    help="Path to function JSON file",
)
@click.pass_context
def deploy_language_rt(ctx, runtime, sdk, function_json, no_rootfs):
    """Deploy language runtime executor function

    You can override any JSON field using dot notation, for example:
    yrcli deploy-language-rt --runtime python3.11 --cpu=1000 --memory=1024 --rootfs.storageInfo.accessKey=mykey
    yrcli deploy-language-rt --runtime python3.11 --rootfs.storageInfo.object=rootfs_python3.11.img

    Naming rules:
    - sdk + python3.x -> 0-defaultservice-py3xx (e.g. python3.11 -> py311, python3.9 -> py39)
    - non-sdk -> 0-system-faasExecutorPython3.x

    Hook handler defaults:
    - sdk -> yrlib_handler.*
    - non-sdk -> faas_executor.*
    Or provide a function JSON file directly with --function-json
    """

    # Get extra arguments from context
    overrides = ctx.args

    # Determine which user to use
    current_user = "12345678901234561234567890123456"

    # If function_json is provided, load it as base configuration
    if function_json:
        with open(function_json, "r") as f:
            function_json_data = json.load(f)
    else:
        # Validate runtime is provided when not using function_json
        if not runtime:
            print("Error: --runtime is required when not using --function-json")
            sys.exit(1)

        # Generate function name based on runtime and sdk flag
        # sdk + python3.x -> 0-defaultservice-py3xx (e.g. python3.11 -> py311, python3.9 -> py39)
        if sdk and runtime.startswith("python3."):
            runtime_suffix = f"py{runtime.replace('python', '').replace('.', '')}"
            function_name = f"0-defaultservice-{runtime_suffix}"
        else:
            # python3.11 -> 0-system-faasExecutorPython3.11
            runtime_name = runtime[0].upper() + runtime[1:]  # Capitalize first letter
            function_name = f"0-system-faasExecutor{runtime_name}"

        # Build default function configuration based on the template
        if sdk:
            hook_handler = {
                "call": "yrlib_handler.call",
                "checkpoint": "yrlib_handler.checkpoint",
                "init": "yrlib_handler.init",
                "recover": "yrlib_handler.recover",
                "shutdown": "yrlib_handler.shutdown",
                "signal": "yrlib_handler.signal",
            }
        else:
            hook_handler = {
                "call": "faas_executor.faasCallHandler",
                "checkpoint": "faas_executor.faasCheckPointHandler",
                "init": "faas_executor.faasInitHandler",
                "recover": "faas_executor.faasRecoverHandler",
                "shutdown": "faas_executor.faasShutDownHandler",
                "signal": "faas_executor.faasSignalHandler",
            }
        function_json_data = {
            "name": function_name,
            "runtime": runtime,
            "kind": "yrlib",
            "cpu": 600,
            "memory": 512,
            "timeout": 600,
            "storageType": "local",
            "codePath": "/var/task",
            "hookHandler": hook_handler,
            "warmup": "seed",
            "rootfs": {
                "runtime": "runsc",
                "type": "s3",
                "imageurl": f"registry.cn-hangzhou.com",
                "readonly": True,
                "mountpoint": "/var/task/code",
                "storageInfo": {
                    "endpoint": "cn-hangzhou.alipay.aliyun-inc.com",
                    "bucket": "crfs-dev",
                    "object": f"rootfs.img",
                },
            },
        }

    # Apply overrides from command line arguments using dot notation
    # Example: --rootfs.storageInfo.accessKey=mykey
    for override in overrides:
        if override.startswith("--"):
            override = override[2:]  # Remove leading --

        if "=" in override:
            key_path, value = override.split("=", 1)
            keys = key_path.split(".")

            # Navigate to the nested dict and set the value
            current = function_json_data
            for key in keys[:-1]:
                if key not in current:
                    current[key] = {}
                current = current[key]

            # Try to parse value as int, bool, or keep as string
            final_key = keys[-1]
            if value.lower() in ("true", "false"):
                current[final_key] = value.lower() == "true"
            elif value.isdigit():
                current[final_key] = int(value)
            else:
                current[final_key] = value

    if no_rootfs:
        if "rootfs" in function_json_data:
            del function_json_data["rootfs"]
        if "warmup" in function_json_data:
            del function_json_data["warmup"]

    # Get function name from the json data
    function_name = function_json_data.get("name")
    if not function_name:
        print("Error: function name is required in configuration")
        sys.exit(1)

    # Check if function already exists
    version = "$latest"
    full_name = f"{function_name}:{version}"
    query_ret, function_info = query_function(full_name, current_user)

    if query_ret:
        # Update existing function
        function_json_data["revisionId"] = function_info.get("revisionId")
        ret = update_function(function_json_data, current_user)
        if ret[0]:
            name = get_name_from_info(ret[1])
            print(f"Successfully updated FaaS language runtime function: {name}")
            if runtime:
                print(f"Runtime: {runtime}")
        else:
            print(f"Failed to update FaaS language runtime function: {ret[1]['error']}")
            sys.exit(1)
    else:
        # Deploy new function
        ret = deploy_function(function_json_data, current_user)
        if ret[0]:
            name = get_name_from_info(ret[1])
            print(f"Successfully deployed FaaS language runtime function: {name}")
            if runtime:
                print(f"Runtime: {runtime}")
        else:
            print(f"Failed to deploy FaaS language runtime function: {ret[1]}")
            sys.exit(1)


@cli.command("run-spark")
@click.option(
    "--script",
    required=True,
    type=str,
    help="Path to the Python script to run with Spark",
)
@click.option(
    "--args",
    required=False,
    type=str,
    default="",
    help="Arguments to pass to the Spark job",
)
def run_spark(script, args):
    """Run a Python script with Spark job

    Example:
        yrcli run-spark --script /path/to/script.py
        yrcli run-spark --script /path/to/script.py --args "arg1 arg2 arg3"
    """
    # Validate script path
    if not os.path.exists(script):
        print(f"Error: Script file not found: {script}")
        sys.exit(1)

    # Get absolute path
    script_path = os.path.abspath(script)
    # Build Java command
    cmd = [
        "java",
        "-cp",
        "/home/yuanrong/sparkjob/spark-job.jar",
        f"-Dentry.point.path={script_path}",
    ]

    if args:
        cmd.append(f"-Dargs={args}")

    cmd.append("com.SparkJobExample")

    print(f"Running Spark job with script: {script_path}")
    print(f"Command: {' '.join(cmd)}")

    try:
        # Execute the Java command with stdout/stderr redirected to terminal
        result = subprocess.run(cmd)

        # Check return code
        if result.returncode != 0:
            print(f"\nSpark job failed with exit code: {result.returncode}")
            sys.exit(result.returncode)

    except FileNotFoundError:
        print("Error: Java command not found. Make sure Java is installed and in PATH.")
        sys.exit(1)
    except Exception as e:
        print(f"Error executing Spark job: {str(e)}")
        sys.exit(1)


@cli.command("exec")
@click.option(
    "-i",
    "--stdin",
    required=False,
    type=bool,
    is_flag=True,
    default=False,
    help="Whether to allocate stdin for the instance",
)
@click.option(
    "-t",
    "--tty",
    required=False,
    type=bool,
    is_flag=True,
    default=False,
    help="Whether to allocate a TTY for the instance",
)
@click.option(
    "--verify-server",
    required=False,
    type=bool,
    is_flag=True,
    default=True,
    help="Verify server certificate (default: True)",
)
@click.argument("instance", type=str)
@click.argument("command", type=str)
def exec(stdin, tty, verify_server, instance, command):
    use_ssl = __client_cert is not None and __client_key is not None
    try:
        host, port = __server_address.split(":")
        asyncio.run(
            run_client(
                host,
                port,
                instance=instance,
                command=command,
                tty=tty,
                stdin=stdin,
                user=__user,
                use_ssl=use_ssl,
                cert_file=__client_cert,
                key_file=__client_key,
                ca_file=__ca_cert,
                verify_server=verify_server,
            )
        )
    except KeyboardInterrupt:
        print("\nDisconnected", file=sys.stderr)


@cli.command("runtime_main", context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
def runtime_main():
    """Start the runtime main process
    
    All unknown options will be ignored, allowing the command to run without errors.
    """    
    from yr.main.yr_runtime_main import main as yr_runtime_main
    yr_runtime_main()


def main():
    return cli()


if __name__ == "__main__":
    main()
