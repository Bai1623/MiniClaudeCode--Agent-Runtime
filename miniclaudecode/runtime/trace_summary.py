"""Structured summaries for tool-call trace events."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class SlowToolCall:
    tool_name: str
    turn: int
    duration_ms: int


@dataclass(frozen=True)
class TraceSummary:
    tool_calls: int
    error_counts: Mapping[str, int]
    retry_count: int
    compressed_calls: int
    compression_strategies: Mapping[str, int]
    snippet_truncated_calls: int
    compression_rate: float
    p50_duration_ms: int
    p95_duration_ms: int
    slow_tools: tuple[SlowToolCall, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation used by run artifacts and reports."""
        return {
            "tool_calls": self.tool_calls,
            "error_counts": dict(self.error_counts),
            "retry_count": self.retry_count,
            "compressed_calls": self.compressed_calls,
            "compression_strategies": dict(self.compression_strategies),
            "snippet_truncated_calls": self.snippet_truncated_calls,
            "compression_rate": self.compression_rate,
            "p50_duration_ms": self.p50_duration_ms,
            "p95_duration_ms": self.p95_duration_ms,
            "slow_tools": [
                {
                    "tool_name": call.tool_name,
                    "turn": call.turn,
                    "duration_ms": call.duration_ms,
                }
                for call in self.slow_tools
            ],
        }

    @classmethod
    def from_events(cls, events: list[dict[str, Any]]) -> TraceSummary:
        durations = sorted(int(event["duration_ms"]) for event in events)
        error_counts: dict[str, int] = {}
        for event in events:
            error_type = event.get("error_type")
            if event.get("status") == "error" and error_type:
                name = str(error_type)
                error_counts[name] = error_counts.get(name, 0) + 1

        compressed_calls = sum(bool(event.get("compressed")) for event in events)
        strategies: dict[str, int] = {}
        for event in events:
            if event.get("compressed"):
                strategy = str(event.get("compression_strategy") or "unknown")
                strategies[strategy] = strategies.get(strategy, 0) + 1
        tool_calls = len(events)
        slow_tools = tuple(
            SlowToolCall(
                tool_name=str(event["tool_name"]),
                turn=int(event["turn"]),
                duration_ms=int(event["duration_ms"]),
            )
            for event in sorted(events, key=lambda item: int(item["duration_ms"]), reverse=True)[:3]
        )
        return cls(
            tool_calls=tool_calls,
            error_counts=MappingProxyType(dict(sorted(error_counts.items()))),
            retry_count=sum(bool(event.get("retried")) for event in events),
            compressed_calls=compressed_calls,
            compression_strategies=MappingProxyType(dict(sorted(strategies.items()))),
            snippet_truncated_calls=sum(bool(event.get("snippet_truncated")) for event in events),
            compression_rate=compressed_calls / tool_calls if tool_calls else 0.0,
            p50_duration_ms=_nearest_rank(durations, 50),
            p95_duration_ms=_nearest_rank(durations, 95),
            slow_tools=slow_tools,
        )


def _nearest_rank(sorted_values: list[int], percentile: int) -> int:
    if not sorted_values:
        return 0
    rank = (percentile * len(sorted_values) + 99) // 100
    return sorted_values[rank - 1]
