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
        self._permanent_allows: set[tuple[str, str]] = set()

    def check(self, tool: Tool, params: dict[str, Any]) -> ToolResult | None:
        """Run the permission gauntlet. Returns a ToolResult if denied, None if allowed."""

        # Layer 1: tool-level self-check
        denial = tool.check_permissions(params)
        if denial is not None:
            return ToolResult(output=f"Permission denied: {denial}", is_error=True)

        # Layer 2: mode-based check
        mode = self.config.permission_mode

        if tool.name == "bash":
            command = str(params.get("command", ""))
            for pattern in self.config.denied_patterns:
                if pattern in command:
                    return ToolResult(
                        output=f"Permission denied: command matches denied pattern '{pattern}'",
                        is_error=True,
                    )

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
                    allow_key = _permission_key(tool.name, params)
                    if allow_key in self._permanent_allows:
                        return None
                    decision = self._ask_user(tool.name, params)
                    if decision == "always":
                        self._permanent_allows.add(allow_key)
                        return None
                    if decision != "once":
                        return ToolResult(output="Permission denied: user rejected.", is_error=True)

        # AUTO mode: allow everything that passed layer 1
        return None

    def _is_safe_command(self, command: str) -> bool:
        cmd_lower = command.strip().lower()
        return any(cmd_lower.startswith(safe) for safe in self.config.allowed_commands)

    def _ask_user(self, tool_name: str, params: dict[str, Any]) -> str:
        prompt = _format_permission_prompt(tool_name, params)
        try:
            answer = input(prompt).strip().lower()
            return _parse_permission_answer(answer)
        except (EOFError, KeyboardInterrupt):
            return "deny"


def _permission_key(tool_name: str, params: dict[str, Any]) -> tuple[str, str]:
    if tool_name == "bash":
        return tool_name, str(params.get("command", "")).strip()
    if tool_name in {"write_file", "edit_file"}:
        return tool_name, str(params.get("path", "")).strip()
    return tool_name, repr(sorted(params.items()))


def _format_permission_prompt(tool_name: str, params: dict[str, Any]) -> str:
    lines = [
        "",
        "[Permission Request]",
        f"Tool: {tool_name}",
    ]
    if tool_name == "bash":
        command = str(params.get("command", ""))
        lines.extend([
            f"Command: {command}",
            f"Risk: {_command_risk(command)}",
            "Why: this command is not in the configured safe command allowlist.",
        ])
    elif tool_name in {"write_file", "edit_file"}:
        lines.extend([
            f"Target: {params.get('path', '(unknown)')}",
            "Why: this tool can change files in the workspace.",
        ])
    else:
        lines.append("Why: this tool needs explicit permission in ask mode.")
    lines.append("Choose: [o]nce / [a]lways / [d]eny > ")
    return "\n".join(lines)


def _command_risk(command: str) -> str:
    lowered = command.lower()
    if any(token in lowered for token in ("rm ", "delete", "drop ", "reset", "clean")):
        return "high - destructive command pattern."
    if any(token in lowered for token in ("curl", "wget", "ssh", "scp", "chmod", "chown")):
        return "medium - external access or permission-changing command."
    return "medium - command is outside the safe allowlist."


def _parse_permission_answer(answer: str) -> str:
    if answer in {"o", "once", "y", "yes"}:
        return "once"
    if answer in {"a", "always", "permanent", "p"}:
        return "always"
    return "deny"
