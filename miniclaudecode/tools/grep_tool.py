"""Grep tool -- search file contents with regex.

Distilled from Claude Code's GrepTool: simplified regex search using ripgrep or fallback.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from miniclaudecode.workspace import WorkspacePolicy

from .base import Tool, ToolResult

MAX_MATCHES = 200


class GrepTool(Tool):
    def __init__(self, config: Any | None = None) -> None:
        self.workspace = WorkspacePolicy.from_config(config)

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return "Search file contents using regex. Uses ripgrep (rg) if available, otherwise falls back to Python re."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for."},
                "path": {"type": "string", "description": "Workspace-relative file or directory to search."},
                "include": {"type": "string", "description": "Workspace-relative glob to filter files (e.g. '*.py')."},
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
        try:
            search_path = self.workspace.resolve_path(params.get("path", "."))
        except ValueError as exc:
            return ToolResult(output=str(exc), is_error=True, error_type="workspace_violation")
        include = params.get("include")
        if include:
            include_denial = self.workspace.validate_glob_pattern(include)
            if include_denial is not None:
                return ToolResult(output=include_denial, is_error=True, error_type="workspace_violation")

        if shutil.which("rg"):
            return self._rg_search(pattern, search_path, include)
        return self._python_search(pattern, search_path, include)

    def _rg_search(self, pattern: str, path: Path, include: str | None) -> ToolResult:
        cmd = ["rg", "--no-heading", "--line-number", "--max-count", str(MAX_MATCHES), pattern, str(path)]
        if include:
            cmd.extend(["--glob", include])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = result.stdout.strip()
            if not output:
                return ToolResult(output="No matches found.")
            lines = output.split("\n")
            if len(lines) > MAX_MATCHES:
                lines = lines[:MAX_MATCHES]
                lines.append(f"... (truncated at {MAX_MATCHES} matches)")
            return ToolResult(output="\n".join(lines))
        except Exception as exc:
            return ToolResult(output=f"Error running rg: {exc}", is_error=True)

    def _python_search(self, pattern: str, path: Path, include: str | None) -> ToolResult:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return ToolResult(output=f"Invalid regex: {exc}", is_error=True)

        matches: list[str] = []
        files = [path] if path.is_file() else sorted(path.rglob(include or "*"))

        for fp in files:
            if not fp.is_file():
                continue
            try:
                for i, line in enumerate(fp.read_text(errors="replace").splitlines(), 1):
                    if regex.search(line):
                        matches.append(f"{fp}:{i}:{line.rstrip()}")
                        if len(matches) >= MAX_MATCHES:
                            matches.append(f"... (truncated at {MAX_MATCHES} matches)")
                            return ToolResult(output="\n".join(matches))
            except Exception:
                continue

        if not matches:
            return ToolResult(output="No matches found.")
        return ToolResult(output="\n".join(matches))
