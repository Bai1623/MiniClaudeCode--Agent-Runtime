"""FileRead tool -- read file contents with optional line range.

Distilled from Claude Code's FileReadTool which includes:
  - imageProcessor for binary image files
  - limits module for size caps
  - line-number formatting

Mini version: plain text read with line numbers and size limit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool, ToolResult

MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB


class FileReadTool(Tool):
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file. Returns numbered lines for easy reference."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path to the file."},
                "offset": {"type": "integer", "description": "1-based start line (optional)."},
                "limit": {"type": "integer", "description": "Number of lines to read (optional)."},
            },
            "required": ["path"],
        }

    def execute(self, params: dict[str, Any]) -> ToolResult:
        filepath = Path(params["path"]).expanduser()
        if not filepath.exists():
            return ToolResult(output=f"Error: file not found: {filepath}", is_error=True)
        if not filepath.is_file():
            return ToolResult(output=f"Error: not a file: {filepath}", is_error=True)
        if filepath.stat().st_size > MAX_FILE_SIZE:
            return ToolResult(output=f"Error: file too large (>{MAX_FILE_SIZE} bytes)", is_error=True)
        try:
            lines = filepath.read_text(errors="replace").splitlines(keepends=True)
        except Exception as exc:
            return ToolResult(output=f"Error reading file: {exc}", is_error=True)

        offset = max(1, params.get("offset", 1))
        limit = params.get("limit")
        selected = lines[offset - 1:]
        if limit is not None and limit > 0:
            selected = selected[:limit]

        numbered = []
        for i, line in enumerate(selected, start=offset):
            numbered.append(f"{i:>6}|{line.rstrip()}")
        return ToolResult(output="\n".join(numbered) or "(empty file)")
