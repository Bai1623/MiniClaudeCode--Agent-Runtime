"""Tool result compression helpers."""

from __future__ import annotations

from miniclaudecode.tools.base import ToolResult


def compress_tool_result(
    result: ToolResult,
    max_chars: int,
    head_chars: int,
    tail_chars: int,
) -> ToolResult:
    """Cap oversized tool output while preserving useful head and tail context."""
    if len(result.output) <= max_chars:
        return result

    compressed = (
        result.output[:head_chars]
        + "\n\n... output truncated ...\n"
        + f"Original length: {len(result.output)} chars.\n"
        + f"Showing first {head_chars} chars and last {tail_chars} chars.\n\n"
        + result.output[-tail_chars:]
    )

    metadata = dict(result.metadata)
    metadata["compressed"] = True
    metadata["original_output_chars"] = len(result.output)

    return ToolResult(
        output=compressed,
        is_error=result.is_error,
        error_type=result.error_type,
        metadata=metadata,
    )
