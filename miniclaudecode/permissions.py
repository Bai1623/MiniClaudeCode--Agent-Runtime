"""Permission system -- distilled from Claude Code's 5-layer permission model.

Original 5 layers:
  1. Tool's own checkPermissions() -- e.g. BashTool checks for destructive commands
  2. Settings allowlist/denylist -- glob patterns like Bash(npm:*)
  3. Sandbox policy -- managed path/command/network restrictions
  4. Active permission mode -- may auto-approve or force-ask
  5. Hook overrides -- PreToolUse hooks can approve/block/modify

Mini version keeps 2 layers:
  Layer 1: Tool.check_permissions() -- each tool checks its own params
  Layer 2: PermissionMode -- ask / auto / plan
"""

from __future__ import annotations

from typing import Any

from .config import Config, PermissionMode
from .tools.base import Tool, ToolResult


class PermissionDenied(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class PermissionGate:
    """Two-layer permission gate before tool execution."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def check(self, tool: Tool, params: dict[str, Any]) -> ToolResult | None:
        """Run the permission gauntlet. Returns a ToolResult if denied, None if allowed."""

        # Layer 1: tool-level self-check
        denial = tool.check_permissions(params)
        if denial is not None:
            return ToolResult(output=f"Permission denied: {denial}", is_error=True)

        # Layer 2: mode-based check
        mode = self.config.permission_mode

        if mode == PermissionMode.PLAN:
            write_tools = {"bash", "write_file", "edit_file"}
            if tool.name in write_tools:
                return ToolResult(
                    output=f"Permission denied: '{tool.name}' is blocked in plan (read-only) mode.",
                    is_error=True,
                )

        if mode == PermissionMode.ASK:
            if tool.name == "bash":
                cmd = params.get("command", "")
                if not self._is_safe_command(cmd):
                    if not self._ask_user(tool.name, params):
                        return ToolResult(output="Permission denied: user rejected.", is_error=True)

        # AUTO mode: allow everything that passed layer 1
        return None

    def _is_safe_command(self, command: str) -> bool:
        cmd_lower = command.strip().lower()
        return any(cmd_lower.startswith(safe) for safe in self.config.allowed_commands)

    @staticmethod
    def _ask_user(tool_name: str, params: dict[str, Any]) -> bool:
        detail = ""
        if tool_name == "bash":
            detail = params.get("command", "")
        elif tool_name in ("write_file", "edit_file"):
            detail = params.get("path", "")
        prompt = f"\n[Permission] Allow '{tool_name}'"
        if detail:
            prompt += f": {detail}"
        prompt += "? [y/N] "
        try:
            answer = input(prompt).strip().lower()
            return answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False
