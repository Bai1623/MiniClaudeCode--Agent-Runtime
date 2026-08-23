"""Tool call tracing helpers."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from miniclaudecode.tools.base import ToolResult

MAX_PREVIEW_VALUE_CHARS = 200
REDACTED_INPUT_VALUE = "[REDACTED]"
SENSITIVE_INPUT_KEYS = frozenset({
    "accesstoken",
    "apikey",
    "authorization",
    "clientsecret",
    "cookie",
    "password",
    "passwd",
    "privatekey",
    "refreshtoken",
    "secret",
    "token",
})
FILE_CONTENT_FIELDS = {
    "edit_file": frozenset({"new_string", "old_string"}),
    "write_file": frozenset({"content"}),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _preview_value(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) > MAX_PREVIEW_VALUE_CHARS:
            return value[:MAX_PREVIEW_VALUE_CHARS] + "... (truncated)"
        return value
    if isinstance(value, dict):
        return _preview_mapping(value)
    if isinstance(value, list):
        return [_preview_value(v) for v in value[:20]]
    return value


def _preview_mapping(values: dict[Any, Any]) -> dict[str, Any]:
    return {
        str(key): REDACTED_INPUT_VALUE if _is_sensitive_key(key) else _preview_value(value)
        for key, value in values.items()
    }


def _is_sensitive_key(key: Any) -> bool:
    normalized = "".join(character for character in str(key).lower() if character.isalnum())
    return normalized in SENSITIVE_INPUT_KEYS


def _summarize_content(content: str) -> dict[str, Any]:
    return {
        "chars": len(content),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def build_input_preview(params: dict[str, Any], tool_name: str = "") -> dict[str, Any]:
    """Build a bounded preview of tool input without recording full content."""
    content_fields = FILE_CONTENT_FIELDS.get(tool_name, frozenset())
    preview: dict[str, Any] = {}
    for key, value in params.items():
        field_name = str(key)
        if _is_sensitive_key(field_name):
            preview[field_name] = REDACTED_INPUT_VALUE
        elif field_name in content_fields and isinstance(value, str):
            preview[field_name] = _summarize_content(value)
        else:
            preview[field_name] = _preview_value(value)
    return preview


class TraceRecorder:
    """Append JSONL trace events for tool calls."""

    def __init__(self, enabled: bool = True, trace_dir: str = ".miniclaudecode/traces") -> None:
        self.enabled = enabled
        self.trace_dir = Path(trace_dir)
        self.run_id: str | None = None
        self.trace_file: Path | None = None

    def set_trace_dir(self, trace_dir: str | Path) -> None:
        """Route subsequent trace files to a specific directory."""
        self.trace_dir = Path(trace_dir)
        self.trace_file = None

    def start_run(self) -> str:
        self.run_id = uuid.uuid4().hex
        if self.enabled:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
            self.trace_file = self.trace_dir / f"{self.run_id}.jsonl"
        return self.run_id

    def record_tool_call(
        self,
        *,
        run_id: str,
        turn: int,
        tool_call_id: str,
        tool_name: str,
        params: dict[str, Any],
        result: ToolResult,
        started_at: datetime,
        ended_at: datetime,
    ) -> None:
        if not self.enabled:
            return

        if self.trace_file is None or self.run_id != run_id:
            self.run_id = run_id
            self.trace_dir.mkdir(parents=True, exist_ok=True)
            self.trace_file = self.trace_dir / f"{run_id}.jsonl"

        duration_ms = int((ended_at - started_at).total_seconds() * 1000)
        event = {
            "run_id": run_id,
            "turn": turn,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "status": "error" if result.is_error else "ok",
            "error_type": result.error_type,
            "duration_ms": duration_ms,
            "input_preview": build_input_preview(params, tool_name=tool_name),
            "output_chars": len(result.output),
            "compressed": bool(result.metadata.get("compressed")),
            "original_output_chars": result.metadata.get("original_output_chars"),
            "kept_snippet_lines": result.metadata.get("kept_snippet_lines"),
            "snippet_truncated": result.metadata.get("snippet_truncated"),
            "compression_strategy": result.metadata.get("compression_strategy"),
            "started_at": _format_timestamp(started_at),
            "ended_at": _format_timestamp(ended_at),
        }

        with self.trace_file.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
