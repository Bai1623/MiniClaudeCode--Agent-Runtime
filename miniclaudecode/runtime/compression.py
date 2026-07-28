"""Tool result compression helpers."""

from __future__ import annotations

import re

from miniclaudecode.tools.base import ToolResult

_ATTENTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(error|exception|traceback|failed|fail(ed)?|timeout|timed out)\b",
        r"\b(assert|warning|warn|fatal|panic)\b",
        r"\b(file not found|permission denied|denied)\b",
        r"\btraceback \(most recent call last\):",
        r"^\s*at\s+\w",
        r"^[^\n]*:\d+:\d+\b",
    )
]

_MATCH_LINE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^\s*[^:\n]+:\d+:",
        r".+:\d+:\d+\s",
        r":\d+:\d+:\d+",
    )
]


def _is_grep_match_line(line: str) -> bool:
    for pattern in _MATCH_LINE_PATTERNS:
        if pattern.search(line):
            return True
    return False


def _collect_grep_snippets(lines: list[str], max_snippet_lines: int) -> list[str]:
    if not lines:
        return []

    matches: list[str] = []
    for line in lines:
        if _is_grep_match_line(line):
            matches.append(line)
        if len(matches) >= max_snippet_lines:
            break

    if not matches and lines:
        return lines[:min(max_snippet_lines, len(lines))]
    return matches


def _collect_bash_snippets(lines: list[str], max_snippet_lines: int) -> list[str]:
    if not lines:
        return []

    indices: set[int] = set()
    for i, line in enumerate(lines):
        if _is_attention_line(line):
            start = max(0, i - 2)
            end = min(len(lines), i + 3)
            indices.update(range(start, end))
        if line.startswith("STDERR:"):
            start = max(0, i - 1)
            end = min(len(lines), i + 8)
            indices.update(range(start, end))

    if not indices:
        return []

    selected = sorted(indices)
    return [lines[i] for i in selected[:max_snippet_lines]]


def _is_attention_line(line: str) -> bool:
    for pattern in _ATTENTION_PATTERNS:
        if pattern.search(line):
            return True
    return False


def _collect_snippets(lines: list[str], max_snippet_lines: int, tool_name: str | None = None) -> list[str]:
    if not lines:
        return []

    if tool_name == "grep":
        return _collect_grep_snippets(lines, max_snippet_lines=max_snippet_lines)
    if tool_name == "bash":
        snippets = _collect_bash_snippets(lines, max_snippet_lines=max_snippet_lines)
        if snippets:
            return snippets

    if len(lines) == 1:
        return []

    indices: set[int] = set()
    for i, line in enumerate(lines):
        if _is_attention_line(line):
            start = max(0, i - 1)
            end = min(len(lines), i + 2)
            indices.update(range(start, end))

    if not indices:
        return []

    selected = sorted(indices)
    truncated = selected[:max_snippet_lines]
    return [lines[i] for i in truncated]


def _build_compressed_output(output: str, head: str, tail: str, snippets: list[str]) -> str:
    parts: list[str] = [
        head,
        "\n\n... output truncated ...\n",
        f"Original length: {len(output)} chars.\n",
        f"Showing first {len(head)} chars and last {len(tail)} chars.\n",
    ]
    if snippets:
        parts.append("\n关键片段（上下文）:\n")
        parts.append("\n".join(snippets))
        parts.append("\n")
    parts.append(tail)
    return "".join(parts)


def compress_tool_result(
    result: ToolResult,
    max_chars: int,
    head_chars: int,
    tail_chars: int,
    tool_name: str | None = None,
    snippet_lines: int | None = None,
) -> ToolResult:
    """Cap oversized tool output while preserving useful head and tail context."""
    output = result.output
    if len(output) <= max_chars:
        return result

    head = output[:head_chars]
    tail = output[-tail_chars:] if tail_chars > 0 else ""
    max_snippet_lines = snippet_lines if snippet_lines and snippet_lines > 0 else 80
    snippets = _collect_snippets(output.splitlines(), max_snippet_lines=max_snippet_lines, tool_name=tool_name)
    compressed = _build_compressed_output(output, head, tail, snippets)

    metadata = dict(result.metadata)
    metadata["compressed"] = True
    metadata["original_output_chars"] = len(output)
    metadata["kept_snippet_lines"] = len(snippets)
    if tool_name:
        metadata["snippet_tool"] = tool_name

    return ToolResult(
        output=compressed,
        is_error=result.is_error,
        error_type=result.error_type,
        metadata=metadata,
    )
