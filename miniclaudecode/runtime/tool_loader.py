"""Tool discovery helpers."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass
from typing import Any

from miniclaudecode.tools.base import Tool, ToolManifest


@dataclass(frozen=True)
class ToolSpec:
    manifest: ToolManifest
    tool: Tool | None = None

    @property
    def enabled(self) -> bool:
        return self.manifest.enabled


def discover_tools(
    package_name: str = "miniclaudecode.tools",
    *,
    config: Any | None = None,
    enabled_tools: set[str] | list[str] | None = None,
    disabled_tools: set[str] | list[str] | None = None,
) -> list[Tool]:
    """Discover enabled concrete Tool subclasses from a package."""
    return [
        spec.tool
        for spec in discover_tool_specs(
            package_name,
            config=config,
            enabled_tools=enabled_tools,
            disabled_tools=disabled_tools,
        )
        if spec.enabled and spec.tool is not None
    ]


def discover_tool_specs(
    package_name: str = "miniclaudecode.tools",
    *,
    config: Any | None = None,
    enabled_tools: set[str] | list[str] | None = None,
    disabled_tools: set[str] | list[str] | None = None,
) -> list[ToolSpec]:
    """Discover tool manifests and enabled tool instances from a package."""
    package = importlib.import_module(package_name)
    specs: list[ToolSpec] = []
    enabled_filter = set(enabled_tools or _config_list(config, "enabled_tools"))
    disabled_filter = set(disabled_tools or _config_list(config, "disabled_tools"))

    for module_info in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
        module = importlib.import_module(module_info.name)

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if not _is_concrete_tool_class(obj, module.__name__):
                continue
            tool = _instantiate_tool(obj, config)
            enabled = _is_enabled(tool.name, enabled_filter, disabled_filter)
            specs.append(
                ToolSpec(
                    manifest=tool.to_manifest(enabled=enabled),
                    tool=tool if enabled else None,
                )
            )

    return specs


def _is_concrete_tool_class(obj: type, module_name: str) -> bool:
    if obj is Tool:
        return False
    if not issubclass(obj, Tool):
        return False
    if inspect.isabstract(obj):
        return False
    return obj.__module__ == module_name


def _instantiate_tool(tool_class: type[Tool], config: Any | None) -> Tool:
    signature = inspect.signature(tool_class)
    if "config" in signature.parameters:
        return tool_class(config=config)
    return tool_class()


def _is_enabled(name: str, enabled_filter: set[str], disabled_filter: set[str]) -> bool:
    if enabled_filter and name not in enabled_filter:
        return False
    return name not in disabled_filter


def _config_list(config: Any | None, field_name: str) -> list[str]:
    if config is None:
        return []
    tool_runtime = getattr(config, "tool_runtime", None)
    value = getattr(tool_runtime, field_name, None)
    return list(value or [])
