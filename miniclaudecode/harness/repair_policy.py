"""Deterministic routing for Harness repair attempts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .evaluator import EvaluationReport

RECOVERABLE_ERROR_TYPES = frozenset({
    "execution_error",
    "timeout_error",
    "unknown_tool",
    "validation_error",
})


@dataclass(frozen=True)
class RepairDecision:
    should_retry: bool
    error_types: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "should_retry": self.should_retry,
            "error_types": list(self.error_types),
            "reason": self.reason,
        }


def route_repair(
    report: EvaluationReport,
    tool_error_types: Iterable[str] = (),
) -> RepairDecision:
    """Route a failed evaluation without retrying unsafe or opaque failures."""
    error_types = {
        str(error_type)
        for error_type in tool_error_types
        if isinstance(error_type, str) and error_type
    }
    for check in report.checks:
        metadata = check.metadata
        error_type = metadata.get("error_type")
        if isinstance(error_type, str) and error_type:
            error_types.add(error_type)
        many_error_types = metadata.get("error_types", [])
        if isinstance(many_error_types, list):
            error_types.update(
                value for value in many_error_types if isinstance(value, str) and value
            )

    ordered = tuple(sorted(error_types))
    if not ordered:
        return RepairDecision(True, ordered, "evaluation_failed_without_structured_error")
    if all(error_type in RECOVERABLE_ERROR_TYPES for error_type in ordered):
        return RepairDecision(True, ordered, "all_error_types_recoverable")
    return RepairDecision(False, ordered, "contains_nonrecoverable_or_unknown_error")
