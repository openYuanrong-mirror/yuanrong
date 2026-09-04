#!/usr/bin/env python3
# coding=UTF-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Client-side adapters for the Rust Data Plane Edge CONNECT endpoint."""

import os
import shutil
from pathlib import Path
from typing import NoReturn, Optional

import click


def find_forward_binary() -> Path:
    """Locate the packaged helper without depending on the current directory."""
    configured = os.environ.get("YR_DATA_PLANE_FORWARD_BIN", "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured))
    yr_package = Path(__file__).resolve().parents[1]
    candidates.append(yr_package / "data_plane" / "bin" / "yr-data-plane-forward")
    path_binary = shutil.which("yr-data-plane-forward")
    if path_binary:
        candidates.append(Path(path_binary))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise click.ClickException(
        "yr-data-plane-forward was not found in the openyuanrong data_plane package directory; set "
        "YR_DATA_PLANE_FORWARD_BIN"
    )


def exec_forward(
    arguments: list[str],
    *,
    token: Optional[str],
    tls_ca: Optional[str],
    tls_server_name: Optional[str],
) -> NoReturn:
    """Replace the CLI process with the byte-transparent CONNECT adapter."""
    binary = find_forward_binary()
    environment = os.environ.copy()
    if token is not None:
        environment["YR_TOKEN"] = token
    if tls_ca is not None:
        environment["YR_DATA_PLANE_FORWARD_TLS_CA"] = tls_ca
    if tls_server_name is not None:
        environment["YR_DATA_PLANE_FORWARD_TLS_SERVER_NAME"] = tls_server_name
    os.execve(str(binary), [str(binary), *arguments], environment)
