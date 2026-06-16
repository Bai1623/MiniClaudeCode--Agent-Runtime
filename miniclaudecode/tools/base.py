"""Base tool interface and registry -- distilled from Claude Code's tool architecture.

Original: each tool has an input schema (Zod), permission check, execution logic, and UI renderer.
Mini version: keeps schema + permission check + execution, drops UI renderer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolResult:
    output: str
    is_error: bool = False
    error_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    """Base class for all miniClaudeCode tools.

    Mirrors Claude Code's per-tool interface:
      - name / description / input_schema  -> fed to LLM as tool definitions
      - check_permissions()                -> layer-1 permission gate
      - execute()                          -> actual work
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]: ...

    @property
    def timeout_seconds(self) -> int:
        return 30

    @property
    def retryable(self) -> bool:
        return False

    @property
    def is_read_only(self) -> bool:
        return False

    def check_permissions(self, params: dict[str, Any]) -> str | None:
        """Return None if allowed, or a denial reason string."""
        return None

    def preview(self, params: dict[str, Any]) -> ToolResult | None:
        """Return a preview of the changes this tool would make, if applicable."""
        return None

    @abstractmethod
    def execute(self, params: dict[str, Any]) -> ToolResult: ...

    def to_api_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    """Central registry that collects tool instances and provides lookup."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def api_schemas(self) -> list[dict[str, Any]]:
        return [t.to_api_schema() for t in self._tools.values()]

    @classmethod
    def default(cls) -> "ToolRegistry":
        from miniclaudecode.runtime.tool_loader import discover_tools

        registry = cls()
        for tool in discover_tools():
            registry.register(tool)
        return registry
