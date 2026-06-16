"""Tool call tracing helpers."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from miniclaudecode.tools.base import ToolResult

MAX_PREVIEW_VALUE_CHARS = 200


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
        return {str(k): _preview_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_preview_value(v) for v in value[:20]]
    return value


def build_input_preview(params: dict[str, Any]) -> dict[str, Any]:
    """Build a bounded preview of tool input without recording full content."""
    return {str(key): _preview_value(value) for key, value in params.items()}


class TraceRecorder:
    """Append JSONL trace events for tool calls."""

    def __init__(self, enabled: bool = True, trace_dir: str = ".miniclaudecode/traces") -> None:
        self.enabled = enabled
        self.trace_dir = Path(trace_dir)
        self.run_id: str | None = None
        self.trace_file: Path | None = None

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
            "input_preview": build_input_preview(params),
            "output_chars": len(result.output),
            "compressed": bool(result.metadata.get("compressed")),
            "started_at": _format_timestamp(started_at),
            "ended_at": _format_timestamp(ended_at),
        }

        with self.trace_file.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
