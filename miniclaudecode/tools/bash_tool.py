"""Bash tool -- execute shell commands with safety checks.

Distilled from Claude Code's BashTool which includes:
  - commandSemantics analysis
  - destructiveCommandWarning
  - bashSecurity / bashPermissions
  - sedValidation / pathValidation / modeValidation
  - sandbox support (shouldUseSandbox)

Mini version: simple subprocess call with deny-pattern matching.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from typing import Any

from miniclaudecode.workspace import WorkspacePolicy

from .base import Tool, ToolResult


class BashTool(Tool):
    DANGEROUS_PATTERNS = [
        "rm -rf /", "rm -rf ~", "sudo rm",
        "git push --force", "git reset --hard",
        "> /dev/sda", "mkfs", "dd if=",
        ":(){ :|:& };:",
    ]

    def __init__(self, config: Any | None = None) -> None:
        self.workspace = WorkspacePolicy.from_config(config)
        self._process_lock = threading.Lock()
        self._active_process: subprocess.Popen[str] | None = None
        self._cancelled_process_ids: set[int] = set()

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "Execute a bash command. Use for running scripts, installing packages, "
            "git operations, and any shell task. Commands run in the configured workspace root."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute.",
                },
            },
            "required": ["command"],
        }

    def check_permissions(self, params: dict[str, Any]) -> str | None:
        cmd = params.get("command", "")
        workspace_denial = self.workspace.validate_command(cmd)
        if workspace_denial is not None:
            return workspace_denial
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern in cmd:
                return f"Blocked: command matches dangerous pattern '{pattern}'"
        return None

    def execute(self, params: dict[str, Any]) -> ToolResult:
        command = params.get("command", "")
        command = _normalize_command(command)
        if not command.strip():
            return ToolResult(output="Error: empty command", is_error=True)
        workspace_denial = self.workspace.validate_command(command)
        if workspace_denial is not None:
            return ToolResult(
                output=f"Permission denied: {workspace_denial}",
                is_error=True,
                error_type="workspace_violation",
            )
        denial = self.check_permissions(params)
        if denial is not None:
            return ToolResult(output=f"Permission denied: {denial}", is_error=True, error_type="permission_denied")
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.workspace.root,
                **self._process_group_options(),
            )
            with self._process_lock:
                self._active_process = process
            stdout, stderr = process.communicate(timeout=self.timeout_seconds)
            if process.pid in self._cancelled_process_ids:
                return ToolResult(
                    output=f"Error: command timed out after {self.timeout_seconds}s",
                    is_error=True,
                    error_type="timeout_error",
                    metadata={"process_tree_terminated": True},
                )
            output_parts = []
            if stdout:
                output_parts.append(stdout)
            if stderr:
                output_parts.append(f"STDERR:\n{stderr}")
            output = "\n".join(output_parts) or "(no output)"
            output = self._normalize_output(output)
            if len(output) > 50_000:
                output = output[:50_000] + "\n... (truncated)"
            return ToolResult(output=output, is_error=process.returncode != 0)
        except subprocess.TimeoutExpired:
            if process is not None:
                self._terminate_process_tree(process)
                stdout, stderr = process.communicate()
                output = self._normalize_output(_combine_output(stdout, stderr))
            else:
                output = ""
            return ToolResult(
                output=(f"Error: command timed out after {self.timeout_seconds}s\n{output}").rstrip(),
                is_error=True,
                error_type="timeout_error",
                metadata={"process_tree_terminated": True},
            )
        except Exception as exc:
            return ToolResult(output=f"Error: {exc}", is_error=True)
        finally:
            if process is not None:
                with self._process_lock:
                    if self._active_process is process:
                        self._active_process = None
                    self._cancelled_process_ids.discard(process.pid)

    def cancel(self) -> bool:
        """Terminate the active shell and its descendants after a runtime timeout."""
        with self._process_lock:
            process = self._active_process
            if process is None or process.poll() is not None:
                return False
            self._cancelled_process_ids.add(process.pid)
        self._terminate_process_tree(process)
        return True

    @staticmethod
    def _process_group_options() -> dict[str, Any]:
        if sys.platform == "win32":
            return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        return {"start_new_session": True}

    def _terminate_process_tree(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        self._cancelled_process_ids.add(process.pid)
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGTERM)

    def _normalize_output(self, output: str) -> str:
        posix_root = self.workspace.root.as_posix()
        native_root = str(self.workspace.root)
        if posix_root != native_root:
            output = output.replace(posix_root, native_root)
        return output


def _normalize_command(command: str) -> str:
    if sys.platform == "win32" and command == "python3":
        return "python"
    if sys.platform == "win32" and command.startswith("python3 "):
        return "python " + command[len("python3 ") :]
    return command


def _combine_output(stdout: str | bytes | None, stderr: str | bytes | None) -> str:
    def decode(value: str | bytes | None) -> str:
        return value.decode(errors="replace") if isinstance(value, bytes) else value or ""

    output_parts = [decode(stdout)]
    if decoded_stderr := decode(stderr):
        output_parts.append(f"STDERR:\n{decoded_stderr}")
    return "\n".join(part for part in output_parts if part) or "(no output)"
