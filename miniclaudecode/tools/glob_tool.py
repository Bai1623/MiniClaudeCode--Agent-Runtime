"""Glob tool -- find files matching a pattern.

Distilled from Claude Code's GlobTool: simplified recursive glob.
"""

from __future__ import annotations

from typing import Any

from miniclaudecode.workspace import WorkspacePolicy

from .base import Tool, ToolResult

MAX_RESULTS = 500


class GlobTool(Tool):
    def __init__(self, config: Any | None = None) -> None:
        self.workspace = WorkspacePolicy.from_config(config)

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return "Find files matching a glob pattern. Returns matching file paths sorted by modification time."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g. '**/*.py'). Patterns without '**/' are auto-prefixed.",
                },
                "directory": {
                    "type": "string",
                    "description": "Workspace-relative directory to search in (default: workspace root).",
                },
            },
            "required": ["pattern"],
        }

    @property
    def retryable(self) -> bool:
        return True

    @property
    def is_read_only(self) -> bool:
        return True

    def execute(self, params: dict[str, Any]) -> ToolResult:
        pattern = params["pattern"]
        pattern_denial = self.workspace.validate_glob_pattern(pattern)
        if pattern_denial is not None:
            return ToolResult(output=pattern_denial, is_error=True, error_type="workspace_violation")
        try:
            directory = self.workspace.resolve_directory(params.get("directory", "."))
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True, error_type="workspace_violation")

        if not directory.is_dir():
            return ToolResult(output=f"Error: directory not found: {directory}", is_error=True)

        if not pattern.startswith("**/") and "/" not in pattern:
            pattern = f"**/{pattern}"

        try:
            matches = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception as exc:
            return ToolResult(output=f"Error: {exc}", is_error=True)

        if not matches:
            return ToolResult(output="No files matched.")

        lines = [str(p) for p in matches[:MAX_RESULTS]]
        if len(matches) > MAX_RESULTS:
            lines.append(f"... and {len(matches) - MAX_RESULTS} more")
        return ToolResult(output="\n".join(lines))
