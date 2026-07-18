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

import subprocess
import sys
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
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=self.workspace.root,
            )
            output_parts = []
            if result.stdout:
                output_parts.append(result.stdout)
            if result.stderr:
                output_parts.append(f"STDERR:\n{result.stderr}")
            output = "\n".join(output_parts) or "(no output)"
            output = self._normalize_output(output)
            if len(output) > 50_000:
                output = output[:50_000] + "\n... (truncated)"
            return ToolResult(output=output, is_error=result.returncode != 0)
        except subprocess.TimeoutExpired:
            return ToolResult(output="Error: command timed out after 120s", is_error=True)
        except Exception as exc:
            return ToolResult(output=f"Error: {exc}", is_error=True)

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
