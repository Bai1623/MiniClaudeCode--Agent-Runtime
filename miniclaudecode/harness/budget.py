"""Trace-backed resource budgets for long-running harness runs."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .artifacts import RunArtifacts, read_jsonl


@dataclass(frozen=True)
class RunBudget:
    max_api_calls: int | None = None
    max_tool_calls: int | None = None
    max_total_tokens: int | None = None
    max_duration_seconds: float | None = None
    max_cost_usd: float | None = None

    def __post_init__(self) -> None:
        for name in ("max_api_calls", "max_tool_calls", "max_total_tokens"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer or null.")
        for name in ("max_duration_seconds", "max_cost_usd"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive number or null.")

    def to_dict(self) -> dict[str, int | float | None]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RunBudget:
        return cls(**{name: value.get(name) for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class BudgetUsage:
    api_calls: int
    tool_calls: int
    total_tokens: int
    elapsed_seconds: float
    estimated_cost_usd: float | None
    cost_available: bool

    def to_dict(self) -> dict[str, int | float | bool | None]:
        return asdict(self)


class BudgetExceededError(RuntimeError):
    def __init__(self, violations: list[str], usage: BudgetUsage) -> None:
        self.violations = tuple(violations)
        self.usage = usage
        super().__init__("Harness budget exhausted: " + "; ".join(violations))


class BudgetTracker:
    def __init__(
        self,
        artifacts: RunArtifacts,
        budget: RunBudget,
        *,
        elapsed_base: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.artifacts = artifacts
        self.budget = budget
        self.elapsed_base = elapsed_base
        self.clock = clock
        self.started_at = clock()

    def usage(self) -> BudgetUsage:
        model_calls = read_jsonl(self.artifacts.model_calls_path)
        tool_calls: list[dict[str, Any]] = []
        if self.artifacts.traces_dir.is_dir():
            for path in sorted(self.artifacts.traces_dir.glob("*.jsonl")):
                if path != self.artifacts.model_calls_path:
                    tool_calls.extend(read_jsonl(path))
        known_costs = [
            float(call["estimated_cost_usd"])
            for call in model_calls
            if call.get("estimated_cost_usd") is not None
        ]
        cost_available = not model_calls or len(known_costs) == len(model_calls)
        return BudgetUsage(
            api_calls=len(model_calls),
            tool_calls=len(tool_calls),
            total_tokens=sum(
                int(call.get("input_tokens", 0))
                + int(call.get("output_tokens", 0))
                + int(call.get("cache_read_input_tokens", 0))
                for call in model_calls
            ),
            elapsed_seconds=round(
                self.elapsed_base + max(0.0, self.clock() - self.started_at),
                6,
            ),
            estimated_cost_usd=sum(known_costs) if cost_available and model_calls else None,
            cost_available=cost_available,
        )

    def check(self, operation: str = "usage") -> BudgetUsage:
        usage = self.usage()
        projected_api_calls = usage.api_calls + (operation == "model_call")
        projected_tool_calls = usage.tool_calls + (operation == "tool_call")
        violations: list[str] = []
        if self.budget.max_api_calls is not None and projected_api_calls > self.budget.max_api_calls:
            violations.append(f"api_calls={usage.api_calls} limit={self.budget.max_api_calls}")
        if self.budget.max_tool_calls is not None and projected_tool_calls > self.budget.max_tool_calls:
            violations.append(f"tool_calls={usage.tool_calls} limit={self.budget.max_tool_calls}")
        if self.budget.max_total_tokens is not None and (
            usage.total_tokens > self.budget.max_total_tokens
            or (operation == "model_call" and usage.total_tokens >= self.budget.max_total_tokens)
        ):
            violations.append(
                f"total_tokens={usage.total_tokens} limit={self.budget.max_total_tokens}"
            )
        if (
            self.budget.max_duration_seconds is not None
            and usage.elapsed_seconds >= self.budget.max_duration_seconds
        ):
            violations.append(
                f"elapsed_seconds={usage.elapsed_seconds} "
                f"limit={self.budget.max_duration_seconds}"
            )
        if self.budget.max_cost_usd is not None:
            if usage.api_calls and not usage.cost_available:
                violations.append("estimated_cost_usd unavailable while a cost limit is configured")
            elif usage.estimated_cost_usd is not None and (
                usage.estimated_cost_usd > self.budget.max_cost_usd
                or (
                    operation == "model_call"
                    and usage.estimated_cost_usd >= self.budget.max_cost_usd
                )
            ):
                violations.append(
                    f"estimated_cost_usd={usage.estimated_cost_usd} "
                    f"limit={self.budget.max_cost_usd}"
                )
        if violations:
            raise BudgetExceededError(violations, usage)
        return usage

    def snapshot(self, *, status: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": status,
            "limits": self.budget.to_dict(),
            "usage": self.usage().to_dict(),
        }


def load_persisted_budget(path: Path, fallback: RunBudget) -> tuple[RunBudget, float]:
    if not path.is_file():
        return fallback, 0.0
    value = json.loads(path.read_text(encoding="utf-8"))
    limits = value.get("limits", {}) if isinstance(value, dict) else {}
    usage = value.get("usage", {}) if isinstance(value, dict) else {}
    budget = RunBudget.from_dict(limits) if isinstance(limits, dict) else fallback
    elapsed = float(usage.get("elapsed_seconds", 0.0)) if isinstance(usage, dict) else 0.0
    return budget, elapsed
