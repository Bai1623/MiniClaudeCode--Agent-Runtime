"""Tool input schema validation helpers."""

from __future__ import annotations

from jsonschema import ValidationError, validate

from miniclaudecode.tools.base import Tool, ToolResult


def validate_tool_input(tool: Tool, params: dict) -> ToolResult | None:
    """Validate model-provided tool input against the tool JSON schema."""
    try:
        validate(instance=params, schema=tool.input_schema)
    except ValidationError as exc:
        return ToolResult(
            output=f"Invalid input for tool '{tool.name}': {exc.message}",
            is_error=True,
            error_type="validation_error",
        )
    return None
