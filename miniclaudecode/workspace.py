"""Workspace path policy for tool execution."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

ABSOLUTE_PATH_RE = re.compile(r"(^|[=:'\"])/")
HOME_PATH_RE = re.compile(r"(^|[=:'\"])~")
PARENT_PATH_RE = re.compile(r"(^|[/=:'\"])\.\.($|[/:'\"])")


class WorkspacePolicy:
    """Restricts tool paths and bash cwd to a configured workspace root."""

    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).expanduser().resolve()

    @classmethod
    def from_config(cls, config: Any | None) -> WorkspacePolicy:
        safety = getattr(config, "safety", None)
        root = getattr(safety, "workspace_root", ".")
        return cls(root)

    def resolve_path(self, raw_path: str | Path, *, label: str = "path") -> Path:
        raw = str(raw_path)
        denial = self.validate_raw_path(raw, label=label)
        if denial is not None:
            raise ValueError(denial)

        candidate = (self.root / raw).resolve()
        if not self.is_inside(candidate):
            raise ValueError(f"Workspace violation: {label} escapes workspace root: {raw}")
        return candidate

    def resolve_directory(self, raw_path: str | Path = ".", *, label: str = "directory") -> Path:
        return self.resolve_path(raw_path, label=label)

    def validate_glob_pattern(self, pattern: str) -> str | None:
        if pattern.startswith("/") or pattern.startswith("~"):
            return "Workspace violation: glob pattern must be relative to the workspace."
        if ".." in Path(pattern).parts:
            return "Workspace violation: glob pattern must not contain '..'."
        return None

    def validate_command(self, command: str) -> str | None:
        try:
            tokens = shlex.split(command)
        except ValueError as exc:
            return f"Invalid shell command: {exc}"

        for token in tokens:
            if token.startswith("~"):
                return "Workspace violation: bash command must not reference home paths."
            if token.startswith("/"):
                return "Workspace violation: bash command must not reference absolute paths."
            if ".." in Path(token).parts:
                return "Workspace violation: bash command must not reference '..' path segments."
            if ABSOLUTE_PATH_RE.search(token):
                return "Workspace violation: bash command must not embed absolute paths."
            if HOME_PATH_RE.search(token) or "$HOME" in token or "${HOME}" in token:
                return "Workspace violation: bash command must not reference home paths."
            if PARENT_PATH_RE.search(token):
                return "Workspace violation: bash command must not reference '..' path segments."
            if "$(" in token or "`" in token:
                return "Workspace violation: bash command must not use shell command substitution."
        return None

    def is_inside(self, path: Path) -> bool:
        return path == self.root or self.root in path.parents

    @staticmethod
    def validate_raw_path(raw_path: str, *, label: str) -> str | None:
        if raw_path.startswith("~"):
            return f"Workspace violation: {label} must not use '~'."
        path = Path(raw_path)
        if path.is_absolute():
            return f"Workspace violation: {label} must be relative to the workspace."
        if ".." in path.parts:
            return f"Workspace violation: {label} must not contain '..'."
        return None
