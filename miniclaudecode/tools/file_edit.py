"""FileEdit tool -- string-replace based editing (like Claude Code's StrReplace).

Distilled from Claude Code's FileEditTool which has:
  - complex diff display
  - types.ts for edit operations
  - utils.ts for fuzzy matching

Mini version: exact old_string -> new_string replacement.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from miniclaudecode.workspace import WorkspacePolicy

from .base import Tool, ToolResult
from .diff_utils import render_unified_diff


class FileEditTool(Tool):
    def __init__(self, config: Any | None = None) -> None:
        self.workspace = WorkspacePolicy.from_config(config)

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Edit a file by replacing an exact string with a new string. "
            "Provide enough context in old_string to uniquely identify the target."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative path to the file to edit."},
                "old_string": {"type": "string", "description": "Exact text to find (must be unique in the file)."},
                "new_string": {"type": "string", "description": "Text to replace it with."},
            },
            "required": ["path", "old_string", "new_string"],
        }

    def _build_new_content(self, params: dict[str, Any]) -> tuple[Path, str, str] | ToolResult:
        try:
            filepath = self.workspace.resolve_path(params["path"])
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True, error_type="workspace_violation")
        old_string = params.get("old_string", "")
        new_string = params.get("new_string", "")

        if not filepath.exists():
            return ToolResult(output=f"Error: file not found: {filepath}", is_error=True)
        if not old_string:
            return ToolResult(output="Error: old_string must not be empty", is_error=True)

        try:
            content = filepath.read_text(errors="replace")
        except Exception as exc:
            return ToolResult(output=f"Error reading file: {exc}", is_error=True)

        count = content.count(old_string)
        if count == 0:
            return ToolResult(output="Error: old_string not found in file", is_error=True)
        if count > 1:
            return ToolResult(
                output=f"Error: old_string found {count} times -- must be unique. Add more context.",
                is_error=True,
            )

        new_content = content.replace(old_string, new_string, 1)
        return filepath, content, new_content

    def preview(self, params: dict[str, Any]) -> ToolResult:
        built = self._build_new_content(params)
        if isinstance(built, ToolResult):
            return built
        filepath, content, new_content = built
        return ToolResult(output=render_unified_diff(filepath, content, new_content))

    def execute(self, params: dict[str, Any]) -> ToolResult:
        built = self._build_new_content(params)
        if isinstance(built, ToolResult):
            return built
        filepath, content, new_content = built
        diff = render_unified_diff(filepath, content, new_content)
        try:
            filepath.write_text(new_content)
        except Exception as exc:
            return ToolResult(output=f"Error writing file: {exc}", is_error=True)

        return ToolResult(output=f"Replaced 1 occurrence in {filepath}\n\nDiff:\n{diff}")
