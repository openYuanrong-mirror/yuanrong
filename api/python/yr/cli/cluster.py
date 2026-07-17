#!/usr/bin/env python3
# coding=UTF-8
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

import sys
import subprocess

import click


DEFAULT_IAM_ADDRESS = "127.0.0.1:31112"
IAM_TOKEN_REQUIRE_PATH = "/iam-server/v1/token/require"
IAM_TOKEN_ABANDON_PATH = "/iam-server/v1/token/abandon"


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
def cli():
    """Cluster-local operation helpers."""


@cli.command("token-require")
@click.option("--tenant-id", required=True, type=str, help="Tenant ID for token generation")
@click.option("--ttl", required=False, type=int, help="Token time-to-live in seconds")
@click.option("--role", required=False, type=str, default="developer", help="Role for the token")
@click.option(
    "--iam-address",
    required=False,
    type=str,
    default=DEFAULT_IAM_ADDRESS,
    envvar="YR_IAM_ADDRESS",
    help="Cluster-local IAM server address",
)
def token_require(tenant_id, ttl, role, iam_address):
    """Request/generate a JWT token by calling iam-server directly inside the cluster."""
    url = f"http://{iam_address}{IAM_TOKEN_REQUIRE_PATH}"
    headers = [f"X-Tenant-ID: {tenant_id}", f"X-Role: {role}"]
    if ttl:
        headers.append(f"X-TTL: {ttl}")

    try:
        response = run_curl("GET", url, headers)
    except subprocess.CalledProcessError as exc:
        sys.stdout.write(f"Token generation failed: {exc}\n")
        raise SystemExit(1) from exc

    token = parse_header(response.stdout, "X-Auth")
    if token:
        sys.stdout.write(f"Token: {token}\n")


@cli.command("token-abandon")
@click.option("--token", required=True, type=str, help="JWT token to abandon/revoke")
@click.option("--tenant-id", required=False, type=str, help="Tenant ID")
@click.option(
    "--iam-address",
    required=False,
    type=str,
    default=DEFAULT_IAM_ADDRESS,
    envvar="YR_IAM_ADDRESS",
    help="Cluster-local IAM server address",
)
def token_abandon(token, tenant_id, iam_address):
    """Abandon/revoke a JWT token by calling iam-server directly inside the cluster."""
    url = f"http://{iam_address}{IAM_TOKEN_ABANDON_PATH}"
    headers = [f"X-Auth: {token}"]
    if tenant_id:
        headers.append(f"X-Tenant-ID: {tenant_id}")

    try:
        run_curl("POST", url, headers)
    except subprocess.CalledProcessError as exc:
        sys.stdout.write(f"Token abandonment failed: {exc}\n")
        raise SystemExit(1) from exc

    sys.stdout.write("Token successfully abandoned/revoked\n")


def run_curl(method, url, headers):
    command = ["curl", "-sS", "--fail", "-D", "-", "-o", "/dev/null", "-X", method]
    for header in headers:
        command.extend(["-H", header])
    command.append(url)
    return subprocess.run(command, check=True, capture_output=True, text=True)


def parse_header(raw_headers, name):
    prefix = name.lower() + ":"
    for line in raw_headers.splitlines():
        if line.lower().startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None


def main():
    cli()


if __name__ == "__main__":
    main()
