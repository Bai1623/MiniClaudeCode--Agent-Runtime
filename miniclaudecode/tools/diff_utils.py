"""Utilities for rendering concise unified diffs."""

from __future__ import annotations

import difflib
from pathlib import Path

MAX_DIFF_CHARS = 20_000


def render_unified_diff(path: Path, old_content: str, new_content: str) -> str:
    """Render a unified diff for a single file."""
    if old_content == new_content:
        return "(no changes)"

    path_label = str(path)
    diff = "".join(difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{path_label}",
        tofile=f"b/{path_label}",
    ))

    if len(diff) > MAX_DIFF_CHARS:
        return diff[:MAX_DIFF_CHARS] + "\n... (diff truncated)"
    return diff
