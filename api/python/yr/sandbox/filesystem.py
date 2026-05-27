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

"""Sandbox filesystem copy operations.

All actual data transfer is delegated to :mod:`yr.cli.exec` so the transport
layer is not duplicated:

* :func:`yr.cli.exec.copy_to_remote` / :func:`~yr.cli.exec.copy_to_remote_streaming`
* :func:`yr.cli.exec.copy_from_remote` / :func:`~yr.cli.exec.copy_from_remote_streaming`
* :func:`yr.cli.exec.choose_cp_mode` – auto mode selection
"""

import asyncio
import os
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from yr.sandbox.sandbox import Sandbox


class CpDirection(Enum):
    """Transfer direction for sandbox copy operations.

    ``UPLOAD``   – copy from local filesystem **into** the sandbox (default).
    ``DOWNLOAD`` – copy from the sandbox **out** to the local filesystem.
    """

    UPLOAD = "upload"
    DOWNLOAD = "download"


def _get_gateway_host() -> str:
    """Return the faasfrontend host:port for exec WebSocket connections.

    Resolution order:
    1. ``YR_GATEWAY_ADDRESS`` environment variable
    2. ``YR_SERVER_ADDRESS`` environment variable
    3. :class:`~yr.config_manager.ConfigManager` ``server_address``
    """
    from yr.config_manager import ConfigManager

    host = os.environ.get("YR_GATEWAY_ADDRESS", "").strip()
    if host:
        return host
    addr = os.environ.get("YR_SERVER_ADDRESS", "").strip()
    if addr:
        return addr
    return ConfigManager().server_address.strip()


class SandboxFilesystem:
    """Namespace for sandbox filesystem copy operations.

    Access via :attr:`~yr.sandbox.sandbox.Sandbox.filesystem`.

    Transport is fully delegated to :mod:`yr.cli.exec` — no duplicate
    implementation of tar/gzip streaming logic.

    Example::

        sb = yr.sandbox.create()

        # Upload a local file into the sandbox
        sb.filesystem.copy_from_local("/local/data.csv", "/sandbox/data.csv")

        # Download a file from the sandbox to a local path
        sb.filesystem.copy_to_local("/sandbox/output.txt", "/local/output.txt")
    """

    def __init__(self, sandbox: "Sandbox") -> None:
        self._sandbox = sandbox

    @staticmethod
    def _env_bool(name: str, default: Optional[bool] = None) -> Optional[bool]:
        """Parse a tri-state boolean env var (true/false/unset)."""
        raw = os.environ.get(name)
        if raw is None:
            return default
        v = raw.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
        return default

    def _resolve_transport_kwargs(self, host: str, port: str) -> dict:
        """Auto-resolve transport kwargs (ssl/token/cert/verify) from yr config.

        Mirrors the logic used by ``yrcli exec`` / ``yrcli cp`` so that
        :meth:`copy_from_local` / :meth:`copy_to_local` honour the same
        configuration already passed to :func:`yr.init`.

        Resolution rules:

        * **use_ssl** — ``True`` if any of: port is ``443``,
          ``ConfigManager.enable_tls`` is set, client cert+key both configured,
          CA file configured, or env ``YR_USE_SSL`` is truthy.
        * **cert_file / key_file / ca_file** — taken from
          ``ConfigManager.certificate_file_path`` / ``private_key_path`` /
          ``verify_file_path`` (empty string → ``None``).
        * **verify_server** — ``True`` by default; ``False`` if env
          ``YR_INSECURE`` is truthy or ``YR_VERIFY_SERVER`` is falsey.
        * **token** — ``ConfigManager.auth_token`` or env ``YR_AUTH_TOKEN``.
        """
        from yr.config_manager import ConfigManager

        cfg = ConfigManager()

        def _nonempty(s):
            s = (s or "").strip()
            return s or None

        cert_file = _nonempty(getattr(cfg, "certificate_file_path", ""))
        key_file = _nonempty(getattr(cfg, "private_key_path", ""))
        ca_file = _nonempty(getattr(cfg, "verify_file_path", ""))
        token = _nonempty(getattr(cfg, "auth_token", "")) or _nonempty(
            os.environ.get("YR_AUTH_TOKEN")
        )

        use_ssl = bool(
            port == "443"
            or getattr(cfg, "enable_tls", False)
            or (cert_file and key_file)
            or ca_file
        )
        env_ssl = self._env_bool("YR_USE_SSL")
        if env_ssl is not None:
            use_ssl = env_ssl

        insecure = self._env_bool("YR_INSECURE", False)
        verify_server = self._env_bool("YR_VERIFY_SERVER", True)
        if insecure:
            verify_server = False

        return {
            "use_ssl": use_ssl,
            "cert_file": cert_file,
            "key_file": key_file,
            "ca_file": ca_file,
            "verify_server": verify_server,
            "token": token,
        }

    def _get_connection(self):
        """Resolve ``(host, port, instance_id, transport_kwargs)`` for exec WS.

        The exec WebSocket is served by faasfrontend, so the address is
        resolved via :func:`_get_gateway_host`, not the bus address used by
        :func:`yr.init`. Transport kwargs (ssl/token/cert/verify) are derived
        from :class:`~yr.config_manager.ConfigManager` and environment
        variables — see :meth:`_resolve_transport_kwargs`.

        Raises:
            RuntimeError: If no server address is configured.
        """
        import yr

        gateway_addr = _get_gateway_host()
        if not gateway_addr:
            raise RuntimeError(
                "Server address is not configured. "
                "Set YR_SERVER_ADDRESS (faasfrontend address) or call yr.init()."
            )
        host, port = gateway_addr.rsplit(":", 1)
        instance_id = yr.get(self._sandbox._instance.get_name.invoke())
        transport_kwargs = self._resolve_transport_kwargs(host, port)
        return host, port, instance_id, transport_kwargs

    def _cp(
        self,
        src: str,
        dst: str,
        direction: CpDirection = CpDirection.UPLOAD,
        streaming: Optional[bool] = None,
    ) -> None:
        """Core copy implementation; delegates to :mod:`yr.cli.exec` transport.

        Args:
            src:       Source path.
            dst:       Destination path.
            direction: ``UPLOAD`` → src is local, dst is sandbox path.
                       ``DOWNLOAD`` → src is sandbox path, dst is local.
            streaming: ``None`` = auto-select, ``True`` = gzip streaming,
                       ``False`` = non-streaming tar.

        Raises:
            FileNotFoundError: Local source not found (upload only).
            RuntimeError: Server address not configured.
        """
        from yr.cli.exec import (
            copy_to_remote,
            copy_from_remote,
            copy_to_remote_streaming,
            copy_from_remote_streaming,
            choose_cp_mode,
        )

        upload = direction == CpDirection.UPLOAD
        local_path = src if upload else dst
        remote_path = dst if upload else src

        if upload and not os.path.exists(local_path):
            raise FileNotFoundError(f"Local source path not found: {local_path}")

        host, port, instance_id, transport_kwargs = self._get_connection()

        if streaming is None:
            streaming = choose_cp_mode(local_path, remote_path, upload=upload)

        if upload:
            fn = copy_to_remote_streaming if streaming else copy_to_remote
            asyncio.run(
                fn(
                    host=host,
                    port=port,
                    instance=instance_id,
                    local_path=local_path,
                    remote_path=remote_path,
                    **transport_kwargs,
                )
            )
        else:
            fn = copy_from_remote_streaming if streaming else copy_from_remote
            asyncio.run(
                fn(
                    host=host,
                    port=port,
                    instance=instance_id,
                    remote_path=remote_path,
                    local_path=local_path,
                    **transport_kwargs,
                )
            )

    def copy_from_local(
        self,
        local_path: str,
        remote_path: str,
        streaming: Optional[bool] = None,
    ) -> None:
        """Copy a local file or directory **into** the sandbox.

        Args:
            local_path:  Absolute or relative path on the **local** machine.
            remote_path: Absolute path inside the **sandbox**.
            streaming:   ``None`` = auto, ``True`` = gzip streaming,
                         ``False`` = non-streaming tar.

        Raises:
            FileNotFoundError: *local_path* does not exist.
            RuntimeError: Server address is not configured.
        """
        self._cp(local_path, remote_path, CpDirection.UPLOAD, streaming)

    def copy_to_local(
        self,
        remote_path: str,
        local_path: str,
        streaming: Optional[bool] = None,
    ) -> None:
        """Copy a file or directory **from** the sandbox to the local machine.

        Args:
            remote_path: Absolute path inside the **sandbox**.
            local_path:  Absolute or relative path on the **local** machine.
            streaming:   ``None`` = auto, ``True`` = gzip streaming,
                         ``False`` = non-streaming tar.

        Raises:
            RuntimeError: Server address is not configured.
        """
        self._cp(remote_path, local_path, CpDirection.DOWNLOAD, streaming)
