"""FileWrite tool -- write content to a file, creating directories as needed.

Distilled from Claude Code's FileWriteTool: simplified to a plain write operation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool, ToolResult


class FileWriteTool(Tool):
    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file. Creates parent directories if they don't exist. Overwrites if the file already exists."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path to the file."},
                "content": {"type": "string", "description": "The content to write."},
            },
            "required": ["path", "content"],
        }

    def execute(self, params: dict[str, Any]) -> ToolResult:
        filepath = Path(params["path"]).expanduser()
        content = params.get("content", "")
        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content)
            return ToolResult(output=f"Wrote {len(content)} chars to {filepath}")
        except Exception as exc:
            return ToolResult(output=f"Error writing file: {exc}", is_error=True)
