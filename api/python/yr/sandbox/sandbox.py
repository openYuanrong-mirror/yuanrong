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

"""Sandbox implementation for isolated code execution."""

import argparse
import subprocess
import tempfile
import os
from typing import Optional, Dict, Any

import yr


@yr.instance
class SandBoxInstance:
    """
    SandBoxInstance class provides isolated environment for code execution.

    This class creates a sandboxed environment where code can be executed
    with limited permissions and resource constraints.

    This is the underlying instance class decorated with @yr.instance.
    Users should typically use the SandBox wrapper class instead.
    """

    def __init__(
        self, working_dir: Optional[str] = None, env: Optional[Dict[str, str]] = None
    ):
        """
        Initialize the SandBox instance.

        Args:
            working_dir (Optional[str]): The working directory for sandbox execution.
                If None, a temporary directory will be created.
            env (Optional[Dict[str, str]]): Environment variables for the sandbox.
                If None, inherits from parent process.
        """
        if working_dir is None:
            self.working_dir = tempfile.mkdtemp(prefix="yr_sandbox_")
            self._temp_dir_created = True
        else:
            self.working_dir = working_dir
            self._temp_dir_created = False

        self.env = env if env is not None else os.environ.copy()
        self._initialized = True

    def execute(self, command: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        """
        Execute a command in the sandbox environment.

        Args:
            command (str): The command to execute.
            timeout (Optional[int]): Timeout in seconds for command execution.
                If None, no timeout is set.

        Returns:
            Dict[str, Any]: A dictionary containing:
                - returncode (int): The return code of the command.
                - stdout (str): Standard output of the command.
                - stderr (str): Standard error of the command.

        Raises:
            RuntimeError: If the sandbox is not initialized.
            subprocess.TimeoutExpired: If the command execution times out.

        Examples:
            >>> sandbox = yr.sandbox.SandBox.invoke()
            >>> result = yr.get(sandbox.execute.invoke("ls -la"))
            >>> print(result['stdout'])
        """
        if not self._initialized:
            raise RuntimeError("SandBox is not initialized")

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.working_dir,
                env=self.env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired as e:
            return {
                "returncode": -1,
                "stdout": e.stdout.decode() if e.stdout else "",
                "stderr": f"Command timed out after {timeout} seconds",
            }
        except Exception as e:
            return {"returncode": -1, "stdout": "", "stderr": str(e)}

    def get_working_dir(self) -> str:
        """
        Get the working directory of the sandbox.

        Returns:
            str: The path to the working directory.
        """
        return self.working_dir

    def cleanup(self) -> None:
        """
        Cleanup the sandbox environment.

        This method removes temporary files and directories created by the sandbox.
        """
        if self._temp_dir_created and os.path.exists(self.working_dir):
            import shutil

            try:
                shutil.rmtree(self.working_dir)
            except Exception as e:
                # Log the error but don't raise
                print(
                    f"Warning: Failed to cleanup sandbox directory {self.working_dir}: {e}"
                )

    def get_name(self):
        """
        Get the name of the sandbox instance.

        Returns:
            str: The name of the sandbox instance.
        """
        return os.environ.get("INSTANCE_ID", "")

    def __del__(self):
        """Destructor to ensure cleanup on object deletion."""
        self.cleanup()


def create(working_dir: Optional[str] = None, env: Optional[Dict[str, str]] = None):
    """
    Create a new SandBox instance.

    This is a convenience function to create a sandbox without using the class directly.

    Args:
        working_dir (Optional[str]): The working directory for sandbox execution.
            If None, a temporary directory will be created.
        env (Optional[Dict[str, str]]): Environment variables for the sandbox.
            If None, inherits from parent process.

    Returns:
        SandBox wrapper instance.

    Examples:
        >>> import yr
        >>> yr.init()
        >>>
        >>> sandbox = yr.sandbox.create()
        >>> result = yr.get(sandbox.exec("pwd"))
        >>> print(result['stdout'])
        >>>
        >>> sandbox.terminate()
        >>> yr.finalize()
    """
    return SandBox(working_dir, env)


class SandBox:
    """
    SandBox wrapper class for convenient sandbox operations.

    This class wraps the SandBoxInstance to provide a simpler interface
    for sandbox operations.

    Examples:
        >>> import yr
        >>> yr.init()
        >>>
        >>> sandbox = yr.sandbox.SandBox()
        >>> result = yr.get(sandbox.exec("echo 'Hello from sandbox'"))
        >>> print(result['stdout'])
        >>>
        >>> sandbox.terminate()
        >>> yr.finalize()
    """

    def __init__(
        self, working_dir: Optional[str] = None, env: Optional[Dict[str, str]] = None
    ):
        """
        Initialize the SandBox wrapper.

        Args:
            working_dir (Optional[str]): The working directory for sandbox execution.
                If None, a temporary directory will be created.
            env (Optional[Dict[str, str]]): Environment variables for the sandbox.
                If None, inherits from parent process.
        """
        self._instance = SandBoxInstance.invoke(working_dir, env)

    def exec(self, command: str, timeout: Optional[int] = None):
        """
        Execute a command in the sandbox environment.

        Args:
            command (str): The command to execute.
            timeout (Optional[int]): Timeout in seconds for command execution.
                If None, no timeout is set.

        Returns:
            ObjectRef: Reference to the execution result that needs to be unwrapped with yr.get().
                The result is a dictionary containing:
                - returncode (int): The return code of the command.
                - stdout (str): Standard output of the command.
                - stderr (str): Standard error of the command.

        Examples:
            >>> sandbox = yr.sandbox.SandBox()
            >>> result_ref = sandbox.exec("ls -la")
            >>> result = yr.get(result_ref)
            >>> print(result['stdout'])
        """
        return self._instance.execute.invoke(command, timeout)

    def get_working_dir(self):
        """
        Get the working directory of the sandbox.

        Returns:
            ObjectRef: Reference to the working directory path.
        """
        return self._instance.get_working_dir.invoke()

    def cleanup(self):
        """
        Cleanup the sandbox environment.

        Returns:
            ObjectRef: Reference to the cleanup result.
        """
        return self._instance.cleanup.invoke()

    def terminate(self):
        """
        Terminate the sandbox instance.

        This will cleanup resources and terminate the remote instance.
        """
        self._instance.terminate()

    def __del__(self):
        """
        Destructor to ensure cleanup and termination on object deletion.

        Automatically calls cleanup() and terminate() when the SandBox object is deleted.
        """
        try:
            if hasattr(self, "_instance") and self._instance is not None:
                # Call cleanup first
                yr.get(self.cleanup())
                # Then terminate the instance
                self.terminate()
        except Exception as e:
            # Silently catch exceptions during cleanup to avoid errors in destructor
            pass


def main():
    parser = argparse.ArgumentParser(description="Create a detached sandbox instance")
    parser.add_argument(
        "--name", type=str, default=None, help="Name of the sandbox instance"
    )
    parser.add_argument(
        "--namespace",
        type=str,
        default="detached.sandbox",
        help="Namespace for the sandbox instance",
    )
    args = parser.parse_args()

    cfg = yr.Config()
    cfg.in_cluster = True
    yr.init(cfg)
    try:
        opt = yr.InvokeOptions()
        opt.custom_extensions["lifecycle"] = "detached"
        opt.idle_timeout = 60 * 60 * 24 * 7
        opt.name = args.name
        opt.namespace = args.namespace
        if not opt.name:
            opt.name = str(uuid.uuid4())

        sandbox = SandBoxInstance.options(opt).invoke()
        try:
            name = yr.get(sandbox.get_name.invoke())
            print(f"sandbox created, instance_name={name}")
        except Exception as e:
            print(f"sandbox create failed, name={opt.name}, error={e}")
    finally:
        yr.finalize()


if __name__ == "__main__":
    main()
