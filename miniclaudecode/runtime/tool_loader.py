"""Tool discovery helpers."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from miniclaudecode.tools.base import Tool


def discover_tools(package_name: str = "miniclaudecode.tools") -> list[Tool]:
    """Discover concrete Tool subclasses from a package."""
    package = importlib.import_module(package_name)
    tools: list[Tool] = []

    for module_info in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
        module = importlib.import_module(module_info.name)

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is Tool:
                continue
            if not issubclass(obj, Tool):
                continue
            if inspect.isabstract(obj):
                continue
            if obj.__module__ != module.__name__:
                continue

            tools.append(obj())

    return tools
