"""Compare two persisted evaluation batches and render reviewable reports."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

COMPARISON_SCHEMA_VERSION = 1
_METRIC_SPECS = (
    ("pass_metrics.pass@1", "Pass@1", "higher"),
    ("pass_metrics.pass@k", "Pass@k", "higher"),
    ("pass_metrics.pass^k", "Pass^k", "higher"),
    ("usage.total_tokens.mean", "Mean total tokens", "lower"),
    ("usage.estimated_cost_usd.mean", "Mean estimated cost (USD)", "lower"),
    ("latency.trial_duration_ms.p50", "Median trial duration (ms)", "lower"),
    ("latency.trial_duration_ms.p95", "P95 trial duration (ms)", "lower"),
    ("tools.calls_per_trial.mean", "Mean tool calls per trial", "lower"),
    ("tools.error_rate", "Tool error rate", "lower"),
    ("errors.agent_failure_rate", "Agent failure rate", "lower"),
    ("errors.grader_error_rate", "Grader error rate", "lower"),
    ("errors.infrastructure_error_rate", "Infrastructure error rate", "lower"),
    ("errors.grader_assertion_failure_rate", "Grader assertion failure rate", "lower"),
)


def compare_eval_batches(baseline_path: str | Path, experiment_path: str | Path) -> dict[str, Any]:
    """Load batch summaries and manifests, then compute directional metric changes."""
    baseline_file = Path(baseline_path).resolve()
    experiment_file = Path(experiment_path).resolve()
    baseline = _load_batch(baseline_file)
    experiment = _load_batch(experiment_file)
    _validate_comparable(baseline, experiment)

    baseline_metrics = baseline["summary"].get("metrics", {})
    experiment_metrics = experiment["summary"].get("metrics", {})
    pass_k = min(
        int(baseline_metrics.get("sample_size", 1)),
        int(experiment_metrics.get("sample_size", 1)),
    )
    metrics = [
        _compare_metric(
            path,
            label,
            direction,
            baseline_metrics,
            experiment_metrics,
            pass_k=pass_k,
        )
        for path, label, direction in _METRIC_SPECS
    ]
    available = [metric for metric in metrics if metric["status"] != "unavailable"]
    improvements = sum(metric["status"] == "improved" for metric in available)
    regressions = sum(metric["status"] == "regressed" for metric in available)
    unchanged = sum(metric["status"] == "unchanged" for metric in available)
    if not available:
        outcome = "insufficient_data"
    elif improvements and regressions:
        outcome = "mixed"
    elif improvements:
        outcome = "improved"
    elif regressions:
        outcome = "regressed"
    else:
        outcome = "unchanged"

    warnings = _comparison_warnings(baseline, experiment)
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "outcome": outcome,
        "metric_counts": {
            "improved": improvements,
            "regressed": regressions,
            "unchanged": unchanged,
            "unavailable": len(metrics) - len(available),
        },
        "identity": {
            "case_id": baseline["summary"].get("case_id"),
            "split": baseline["summary"].get("split"),
            "baseline": _batch_identity(baseline),
            "experiment": _batch_identity(experiment),
        },
        "metrics": metrics,
        "confidence_intervals": {
            "baseline_pass@1": _get_path(
                baseline_metrics, "pass_metrics.pass@1_confidence_interval"
            ),
            "experiment_pass@1": _get_path(
                experiment_metrics, "pass_metrics.pass@1_confidence_interval"
            ),
        },
        "warnings": warnings,
        "inputs": {
            "baseline_summary": str(baseline_file),
            "experiment_summary": str(experiment_file),
        },
    }


def render_comparison_markdown(comparison: dict[str, Any]) -> str:
    """Render a compact Markdown report suitable for code review or a README."""
    identity = comparison["identity"]
    baseline = identity["baseline"]
    experiment = identity["experiment"]
    lines = [
        "# Evaluation Batch Comparison",
        "",
        f"- Outcome: **{comparison['outcome']}**",
        f"- Case: `{identity['case_id']}` ({identity['split'] or 'split unavailable'})",
        f"- Baseline batch: `{baseline['batch_id']}`",
        f"- Experiment batch: `{experiment['batch_id']}`",
        f"- Trials: {baseline['completed_trials']}/{baseline['requested_trials']} → "
        f"{experiment['completed_trials']}/{experiment['requested_trials']}",
        "",
        "| Metric | Baseline | Experiment | Change | Assessment |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for metric in comparison["metrics"]:
        lines.append(
            f"| {metric['label']} | {_format_value(metric['baseline'])} | "
            f"{_format_value(metric['experiment'])} | {_format_value(metric['delta'])} | "
            f"{metric['status']} |"
        )
    intervals = comparison.get("confidence_intervals", {})
    baseline_interval = _format_interval(intervals.get("baseline_pass@1"))
    experiment_interval = _format_interval(intervals.get("experiment_pass@1"))
    if baseline_interval or experiment_interval:
        lines.extend(
            (
                "",
                "## Pass@1 uncertainty",
                "",
                f"- Baseline 95% Wilson CI: {baseline_interval or 'unavailable'}",
                f"- Experiment 95% Wilson CI: {experiment_interval or 'unavailable'}",
            )
        )
    lines.extend(("", "## Run identity", ""))
    for label, batch in (("Baseline", baseline), ("Experiment", experiment)):
        lines.append(
            f"- {label}: commit `{batch['commit_sha'] or 'unavailable'}` "
            f"({batch['branch'] or 'branch unavailable'}, dirty={batch['dirty']}), "
            f"model `{batch['model'] or 'unavailable'}`, "
            f"config `{batch['config_sha256'] or 'unavailable'}`"
        )
    if comparison["warnings"]:
        lines.extend(("", "## Warnings", ""))
        lines.extend(f"- {warning}" for warning in comparison["warnings"])
    lines.append("")
    return "\n".join(lines)


def write_comparison_reports(comparison: dict[str, Any], output_prefix: str | Path) -> tuple[Path, Path]:
    """Write JSON and Markdown reports next to the selected output prefix."""
    prefix = Path(output_prefix)
    json_path = prefix.with_suffix(".json")
    markdown_path = prefix.with_suffix(".md")
    input_paths = {
        Path(comparison["inputs"]["baseline_summary"]).resolve(),
        Path(comparison["inputs"]["experiment_summary"]).resolve(),
    }
    if json_path.resolve() in input_paths or markdown_path.resolve() in input_paths:
        raise ValueError("Comparison output must not overwrite either input summary.")
    _atomic_write(json_path, json.dumps(comparison, ensure_ascii=False, indent=2) + "\n")
    _atomic_write(markdown_path, render_comparison_markdown(comparison))
    return json_path, markdown_path


def _load_batch(summary_path: Path) -> dict[str, Any]:
    summary = _read_object(summary_path)
    if not isinstance(summary.get("metrics"), dict):
        raise ValueError(f"Batch summary has no metrics object: {summary_path}")
    manifest_path = summary_path.parent / "experiment_manifest.json"
    manifest = _read_object(manifest_path) if manifest_path.is_file() else None
    return {"summary": summary, "manifest": manifest, "summary_path": summary_path}


def _validate_comparable(baseline: dict[str, Any], experiment: dict[str, Any]) -> None:
    left = baseline["summary"]
    right = experiment["summary"]
    if not left.get("case_id") or left.get("case_id") != right.get("case_id"):
        raise ValueError("Evaluation batches must use the same case_id.")
    if left.get("split") != right.get("split"):
        raise ValueError("Evaluation batches must use the same split.")
    left_case_hash = _manifest_case_hash(baseline["manifest"])
    right_case_hash = _manifest_case_hash(experiment["manifest"])
    if left_case_hash and right_case_hash and left_case_hash != right_case_hash:
        raise ValueError("Evaluation batches have different EvalCase fingerprints.")


def _manifest_case_hash(manifest: dict[str, Any] | None) -> str | None:
    if manifest is None:
        return None
    evaluation = manifest.get("evaluation")
    return evaluation.get("case_sha256") if isinstance(evaluation, dict) else None


def _batch_identity(batch: dict[str, Any]) -> dict[str, Any]:
    summary = batch["summary"]
    manifest = batch["manifest"] or {}
    evaluation = manifest.get("evaluation", {})
    agent = manifest.get("agent", {})
    configuration = manifest.get("configuration", {})
    source = manifest.get("source", {}).get("git", {})
    return {
        "batch_id": summary.get("batch_id"),
        "split": summary.get("split", evaluation.get("split")),
        "requested_trials": summary.get("requested_trials"),
        "completed_trials": summary.get("completed_trials"),
        "commit_sha": source.get("commit_sha"),
        "branch": source.get("branch"),
        "dirty": source.get("dirty"),
        "model": agent.get("model"),
        "config_sha256": configuration.get("sha256"),
        "case_sha256": evaluation.get("case_sha256"),
    }


def _comparison_warnings(baseline: dict[str, Any], experiment: dict[str, Any]) -> list[str]:
    left = _batch_identity(baseline)
    right = _batch_identity(experiment)
    warnings = []
    if left["model"] != right["model"]:
        warnings.append("Model differs between baseline and experiment.")
    if left["config_sha256"] != right["config_sha256"]:
        warnings.append("Configuration fingerprint differs between baseline and experiment.")
    if left["commit_sha"] == right["commit_sha"] and left["commit_sha"] is not None:
        warnings.append("Both batches use the same Git commit.")
    if not left["case_sha256"] or not right["case_sha256"]:
        warnings.append("One or both batches have no experiment manifest; case fingerprint checks were skipped.")
    return warnings


def _compare_metric(
    path: str,
    label: str,
    direction: str,
    baseline: dict[str, Any],
    experiment: dict[str, Any],
    *,
    pass_k: int,
) -> dict[str, Any]:
    metric_path = path
    if path in {"pass_metrics.pass@k", "pass_metrics.pass^k"}:
        metric_path = f"{path}.{pass_k}"
        label = f"{label} (k={pass_k})"
    baseline_value = _get_path(baseline, metric_path)
    experiment_value = _get_path(experiment, metric_path)
    fallback_path = {
        "errors.agent_failure_rate": "errors.task_failure_rate",
        "errors.grader_assertion_failure_rate": "errors.grader_failure_rate",
    }.get(metric_path)
    if fallback_path is not None:
        if baseline_value is None:
            baseline_value = _get_path(baseline, fallback_path)
        if experiment_value is None:
            experiment_value = _get_path(experiment, fallback_path)
    if _is_number(baseline_value) and _is_number(experiment_value):
        baseline_number = float(baseline_value)
        experiment_number = float(experiment_value)
        delta = experiment_number - baseline_number
        relative = delta / baseline_number if baseline_number != 0 else None
        displayed_baseline: float | int | None = baseline_value
        displayed_experiment: float | int | None = experiment_value
    else:
        delta = None
        relative = None
        displayed_baseline = None
        displayed_experiment = None

    if delta is None:
        status = "unavailable"
    elif delta == 0:
        status = "unchanged"
    elif (delta > 0) == (direction == "higher"):
        status = "improved"
    else:
        status = "regressed"
    return {
        "path": metric_path,
        "label": label,
        "direction": direction,
        "baseline": displayed_baseline,
        "experiment": displayed_experiment,
        "delta": round(delta, 6) if delta is not None else None,
        "relative_change": round(relative, 6) if relative is not None else None,
        "status": status,
    }


def _get_path(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read evaluation batch JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _format_value(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _format_interval(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    lower = value.get("lower")
    upper = value.get("upper")
    if (
        isinstance(lower, bool)
        or not isinstance(lower, (int, float))
        or isinstance(upper, bool)
        or not isinstance(upper, (int, float))
    ):
        return None
    return f"[{lower:.4f}, {upper:.4f}]"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)
