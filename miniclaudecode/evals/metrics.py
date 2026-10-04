"""Deterministic aggregate metrics for repeated evaluation trials."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .runner import EvalRunResult


def build_batch_metrics(trials: Sequence[EvalRunResult]) -> dict[str, Any]:
    """Aggregate success, usage, latency, tool, and error metrics."""
    if not trials:
        raise ValueError("At least one trial is required to build eval metrics.")

    sample_size = len(trials)
    successes = sum(trial.passed for trial in trials)
    pass_at_k = {
        str(k): _pass_at_k(sample_size, successes, k)
        for k in range(1, sample_size + 1)
    }
    pass_power_k = {
        str(k): _pass_power_k(sample_size, successes, k)
        for k in range(1, sample_size + 1)
    }

    trial_durations: list[float] = []
    model_calls_per_trial: list[float] = []
    input_tokens: list[float] = []
    output_tokens: list[float] = []
    cache_read_tokens: list[float] = []
    total_tokens: list[float] = []
    estimated_costs: list[float] = []
    tool_calls_per_trial: list[float] = []
    total_tool_calls = 0
    tool_errors = 0
    grader_results = 0
    grader_failures = 0

    for trial in trials:
        trial_dir = trial.artifact_path.parent
        result = _read_json(trial.artifact_path)
        trial_durations.append(float(result.get("duration_ms", 0)))

        model_calls = _read_jsonl(trial_dir / "traces" / "model_calls.jsonl")
        model_calls_per_trial.append(float(len(model_calls)))
        trial_input = sum(_number(event.get("input_tokens")) for event in model_calls)
        trial_output = sum(_number(event.get("output_tokens")) for event in model_calls)
        trial_cache = sum(_number(event.get("cache_read_input_tokens")) for event in model_calls)
        input_tokens.append(trial_input)
        output_tokens.append(trial_output)
        cache_read_tokens.append(trial_cache)
        total_tokens.append(trial_input + trial_output + trial_cache)
        known_costs = [
            float(event["estimated_cost_usd"])
            for event in model_calls
            if event.get("estimated_cost_usd") is not None
        ]
        if model_calls and len(known_costs) == len(model_calls):
            estimated_costs.append(sum(known_costs))

        tool_events = _read_jsonl(trial_dir / "tool_trajectory.jsonl")
        tool_calls_per_trial.append(float(len(tool_events)))
        total_tool_calls += len(tool_events)
        tool_errors += sum(event.get("status") == "error" for event in tool_events)

        grade_report = _read_json(trial_dir / "grader_results.json")
        results = grade_report.get("results", [])
        if isinstance(results, list):
            grader_results += len(results)
            grader_failures += sum(
                isinstance(result, dict) and not bool(result.get("passed"))
                for result in results
            )

    failure_categories = [_failure_category(trial) for trial in trials]
    agent_failures = sum(category == "agent" for category in failure_categories)
    grader_errors = sum(category == "grader" for category in failure_categories)
    infrastructure_errors = sum(category == "infrastructure" for category in failure_categories)
    pass_interval = _wilson_interval(successes, sample_size)
    return {
        "schema_version": 2,
        "sample_size": sample_size,
        "successes": successes,
        "definitions": {
            "pass@k": "Probability of at least one success in k samples without replacement.",
            "pass^k": "Probability that all k samples succeed without replacement.",
            "infrastructure_errors": "Counted as unsuccessful in pass metrics and reported separately.",
            "confidence_intervals": "Two-sided 95% Wilson score intervals for binomial trial rates.",
            "agent_failures": "Candidate execution errors or completed candidates rejected by graders.",
            "grader_errors": "Exceptions raised while executing the grader pipeline.",
            "total_tokens": "Input + output + cache-read tokens.",
            "estimated_cost_usd": "Available only for trials where every model call has a cost estimate.",
        },
        "pass_metrics": {
            "pass@1": _ratio(successes, sample_size),
            "pass@1_confidence_interval": pass_interval,
            "pass@k": pass_at_k,
            "pass^k": pass_power_k,
        },
        "usage": {
            "model_calls": _distribution(model_calls_per_trial),
            "input_tokens": _distribution(input_tokens),
            "output_tokens": _distribution(output_tokens),
            "cache_read_input_tokens": _distribution(cache_read_tokens),
            "total_tokens": _distribution(total_tokens),
            "estimated_cost_usd": {
                "available": bool(estimated_costs),
                "trials_with_estimate": len(estimated_costs),
                **_distribution(estimated_costs),
            },
        },
        "latency": {"trial_duration_ms": _distribution(trial_durations)},
        "tools": {
            "calls_per_trial": _distribution(tool_calls_per_trial),
            "total_calls": total_tool_calls,
            "error_calls": tool_errors,
            "error_rate": _ratio(tool_errors, total_tool_calls),
        },
        "errors": {
            "trial_failure_rate": _ratio(sample_size - successes, sample_size),
            "task_failure_rate": _ratio(agent_failures, sample_size),
            "agent_failure_rate": _ratio(agent_failures, sample_size),
            "agent_failure_confidence_interval": _wilson_interval(agent_failures, sample_size),
            "grader_error_rate": _ratio(grader_errors, sample_size),
            "grader_error_confidence_interval": _wilson_interval(grader_errors, sample_size),
            "infrastructure_error_rate": _ratio(infrastructure_errors, sample_size),
            "infrastructure_error_confidence_interval": _wilson_interval(
                infrastructure_errors, sample_size
            ),
            "grader_failure_rate": _ratio(grader_failures, grader_results),
            "grader_assertion_failure_rate": _ratio(grader_failures, grader_results),
        },
    }


def _failure_category(trial: EvalRunResult) -> str | None:
    if trial.failure_category is not None:
        return trial.failure_category
    if trial.status == "failed":
        return "agent"
    if trial.status == "agent_error":
        return "agent"
    if trial.status == "grader_error":
        return "grader"
    if trial.status == "infrastructure_error":
        return "infrastructure"
    return None


def _wilson_interval(successes: int, sample_size: int) -> dict[str, Any]:
    confidence_level = 0.95
    if sample_size <= 0:
        return {
            "method": "wilson_score",
            "confidence_level": confidence_level,
            "lower": None,
            "upper": None,
        }
    z = 1.959963984540054
    proportion = successes / sample_size
    denominator = 1 + z * z / sample_size
    center = (proportion + z * z / (2 * sample_size)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / sample_size
            + z * z / (4 * sample_size * sample_size)
        )
        / denominator
    )
    return {
        "method": "wilson_score",
        "confidence_level": confidence_level,
        "lower": _rounded(max(0.0, center - margin)),
        "upper": _rounded(min(1.0, center + margin)),
    }


def _pass_at_k(total: int, correct: int, k: int) -> float:
    if total - correct < k:
        return 1.0
    return _rounded(1.0 - math.comb(total - correct, k) / math.comb(total, k))


def _pass_power_k(total: int, correct: int, k: int) -> float:
    if correct < k:
        return 0.0
    return _rounded(math.comb(correct, k) / math.comb(total, k))


def _distribution(values: Sequence[float]) -> dict[str, int | float | None]:
    if not values:
        return {
            "count": 0,
            "total": None,
            "mean": None,
            "min": None,
            "p50": None,
            "p95": None,
            "max": None,
        }
    ordered = sorted(values)
    total = sum(ordered)
    return {
        "count": len(ordered),
        "total": _rounded(total),
        "mean": _rounded(total / len(ordered)),
        "min": _rounded(ordered[0]),
        "p50": _rounded(_nearest_rank(ordered, 50)),
        "p95": _rounded(_nearest_rank(ordered, 95)),
        "max": _rounded(ordered[-1]),
    }


def _nearest_rank(values: Sequence[float], percentile: int) -> float:
    index = max(0, math.ceil(percentile / 100 * len(values)) - 1)
    return values[index]


def _ratio(numerator: int, denominator: int) -> float:
    return _rounded(numerator / denominator) if denominator else 0.0


def _rounded(value: float) -> float:
    return round(float(value), 6)


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in eval artifact: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"Expected JSON objects in eval artifact: {path}")
        events.append(value)
    return events
