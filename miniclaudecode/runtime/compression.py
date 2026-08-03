"""Tool result compression helpers."""

from __future__ import annotations

import re

from miniclaudecode.tools.base import ToolResult

SNIPPET_SECTION_LABEL = "关键片段（上下文）:"
SNIPPET_TRUNCATED_NOTICE = "... 关键片段已截断 ..."

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
        return lines[: min(max_snippet_lines, len(lines))]
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


def _build_snippet_section(snippets: list[str], max_chars: int) -> tuple[str, bool, int]:
    if not snippets or max_chars <= 0:
        return "", False, 0

    selected: list[str] = []
    used = 0
    for i, line in enumerate(snippets):
        add_len = len(line) + (1 if i > 0 else 0)
        if used + add_len > max_chars:
            break
        selected.append(line)
        used += add_len

    if not selected:
        return "", False, 0

    section = "\n".join(selected)
    snippet_truncated = len(selected) < len(snippets)
    if snippet_truncated and used + len(SNIPPET_TRUNCATED_NOTICE) <= max_chars:
        section = f"{section}\n{SNIPPET_TRUNCATED_NOTICE}"

    return f"\n{SNIPPET_SECTION_LABEL}\n{section}\n", snippet_truncated, len(selected)


def _build_compressed_output(
    output: str,
    head: str,
    tail: str,
    snippets: list[str],
    max_chars: int,
) -> tuple[str, bool, int]:
    prefix = (
        head
        + "\n\n... output truncated ...\n"
        + f"Original length: {len(output)} chars.\n"
        + f"Showing first {len(head)} chars and last {len(tail)} chars.\n"
    )

    snippet_budget = max_chars - len(prefix) - len(tail)
    snippet_section, snippet_truncated, kept_snippet_lines = _build_snippet_section(
        snippets=snippets,
        max_chars=snippet_budget,
    )

    compressed = prefix + snippet_section + tail
    if len(compressed) > max_chars:
        head_and_tail_budget = max_chars - len(prefix) - len(snippet_section)
        if head_and_tail_budget > 0:
            compressed = prefix + snippet_section + tail[:head_and_tail_budget]
        else:
            compressed = compressed[:max_chars]

    return compressed, snippet_truncated, kept_snippet_lines


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
    if max_chars <= 0:
        return ToolResult(output="", is_error=result.is_error, error_type=result.error_type)

    max_snippet_lines = snippet_lines if snippet_lines and snippet_lines > 0 else 80
    head_chars = max(0, min(head_chars, max_chars))
    metadata_budget = len("\n\n... output truncated ...\n" "Original length: 0000000000 chars.\n" "Showing first 0 chars and last 0 chars.\n")
    max_tail = max(0, max_chars - metadata_budget - head_chars)
    tail_chars = max(0, min(tail_chars, max_tail))

    head = output[:head_chars]
    tail = output[-tail_chars:] if tail_chars > 0 else ""
    snippets = _collect_snippets(output.splitlines(), max_snippet_lines=max_snippet_lines, tool_name=tool_name)
    compressed, snippet_truncated, kept_snippet_lines = _build_compressed_output(
        output=output,
        head=head,
        tail=tail,
        snippets=snippets,
        max_chars=max_chars,
    )
    if len(compressed) > max_chars:
        compressed = compressed[:max_chars]

    metadata = dict(result.metadata)
    metadata["compressed"] = True
    metadata["original_output_chars"] = len(output)
    metadata["kept_snippet_lines"] = kept_snippet_lines
    metadata["snippet_truncated"] = snippet_truncated
    if tool_name:
        metadata["snippet_tool"] = tool_name

    return ToolResult(
        output=compressed,
        is_error=result.is_error,
        error_type=result.error_type,
        metadata=metadata,
    )
