"""Privacy-safe tracing for model API calls."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODEL_TRACE_SCHEMA_VERSION = 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def build_model_call_event(
    *,
    run_id: str,
    turn: int,
    model: str,
    response: Any,
    started_at: datetime,
    ended_at: datetime,
    input_cost_per_million_usd: float | None = None,
    output_cost_per_million_usd: float | None = None,
    cache_read_cost_per_million_usd: float | None = None,
) -> dict[str, Any]:
    """Create an event without retaining prompts, responses, or API credentials."""
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    cache_read_tokens = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cost: float | None = None
    if input_cost_per_million_usd is not None and output_cost_per_million_usd is not None:
        cost = (input_tokens * input_cost_per_million_usd + output_tokens * output_cost_per_million_usd) / 1_000_000
        if cache_read_cost_per_million_usd is not None:
            cost += cache_read_tokens * cache_read_cost_per_million_usd / 1_000_000
    return {
        "schema_version": MODEL_TRACE_SCHEMA_VERSION,
        "run_id": run_id,
        "turn": turn,
        "model": model,
        "duration_ms": int((ended_at - started_at).total_seconds() * 1000),
        "stop_reason": getattr(response, "stop_reason", None),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cache_read_tokens,
        "estimated_cost_usd": cost,
        "started_at": _timestamp(started_at),
        "ended_at": _timestamp(ended_at),
    }


class ModelCallRecorder:
    """Append model-call events to a dedicated JSONL artifact."""

    def __init__(self, enabled: bool = True, trace_dir: str = ".miniclaudecode/traces") -> None:
        self.enabled = enabled
        self.trace_dir = Path(trace_dir)

    def set_trace_dir(self, trace_dir: str | Path) -> None:
        self.trace_dir = Path(trace_dir)

    def record(self, **kwargs: Any) -> None:
        if not self.enabled:
            return
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        event = build_model_call_event(**kwargs)
        with (self.trace_dir / "model_calls.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
