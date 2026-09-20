"""Tests for repeated-trial evaluation metrics."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from miniclaudecode.evals import EvalRunResult, build_batch_metrics


class TestEvalMetrics(unittest.TestCase):
    def test_aggregates_pass_usage_latency_tool_and_error_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            trials = (
                self._trial(root, 1, "passed", True, 100, 10, 5, 1, 0.01, ["ok", "error"], [True, True]),
                self._trial(root, 2, "passed", True, 200, 20, 8, 2, 0.02, ["ok"], [True, True]),
                self._trial(root, 3, "failed", False, 300, 30, 12, 3, None, [], [True, False]),
            )

            metrics = build_batch_metrics(trials)

        self.assertEqual(metrics["sample_size"], 3)
        self.assertEqual(metrics["pass_metrics"]["pass@1"], 0.666667)
        self.assertEqual(metrics["pass_metrics"]["pass@k"]["2"], 1.0)
        self.assertEqual(metrics["pass_metrics"]["pass^k"]["2"], 0.333333)
        self.assertEqual(metrics["usage"]["input_tokens"]["total"], 60.0)
        self.assertEqual(metrics["usage"]["total_tokens"]["total"], 91.0)
        self.assertEqual(metrics["usage"]["estimated_cost_usd"]["trials_with_estimate"], 2)
        self.assertEqual(metrics["usage"]["estimated_cost_usd"]["total"], 0.03)
        self.assertEqual(metrics["latency"]["trial_duration_ms"]["p50"], 200.0)
        self.assertEqual(metrics["latency"]["trial_duration_ms"]["p95"], 300.0)
        self.assertEqual(metrics["tools"]["total_calls"], 3)
        self.assertEqual(metrics["tools"]["error_rate"], 0.333333)
        self.assertEqual(metrics["errors"]["task_failure_rate"], 0.333333)
        self.assertEqual(metrics["errors"]["infrastructure_error_rate"], 0.0)
        self.assertEqual(metrics["errors"]["grader_failure_rate"], 0.166667)

    def test_missing_price_is_reported_as_unavailable_not_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            trial = self._trial(
                Path(tmpdir), 1, "infrastructure_error", False, 50, 0, 0, 0, None, [], [],
            )

            metrics = build_batch_metrics((trial,))

        cost = metrics["usage"]["estimated_cost_usd"]
        self.assertFalse(cost["available"])
        self.assertIsNone(cost["total"])
        self.assertEqual(metrics["pass_metrics"]["pass@1"], 0.0)
        self.assertEqual(metrics["errors"]["infrastructure_error_rate"], 1.0)

    def test_requires_at_least_one_trial(self):
        with self.assertRaisesRegex(ValueError, "At least one trial"):
            build_batch_metrics(())

    def _trial(
        self,
        root: Path,
        index: int,
        status: str,
        passed: bool,
        duration_ms: int,
        input_tokens: int,
        output_tokens: int,
        cache_tokens: int,
        cost: float | None,
        tool_statuses: list[str],
        grader_statuses: list[bool],
    ) -> EvalRunResult:
        trial_dir = root / f"trial-{index:03d}"
        trace_dir = trial_dir / "traces"
        trace_dir.mkdir(parents=True)
        result_path = trial_dir / "eval_result.json"
        result_path.write_text(json.dumps({"duration_ms": duration_ms}), encoding="utf-8")
        model_event = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_tokens,
            "estimated_cost_usd": cost,
        }
        (trace_dir / "model_calls.jsonl").write_text(
            json.dumps(model_event) + "\n",
            encoding="utf-8",
        )
        (trial_dir / "tool_trajectory.jsonl").write_text(
            "".join(json.dumps({"status": value}) + "\n" for value in tool_statuses),
            encoding="utf-8",
        )
        (trial_dir / "grader_results.json").write_text(
            json.dumps({"results": [{"passed": value} for value in grader_statuses]}),
            encoding="utf-8",
        )
        return EvalRunResult(
            trial_id=f"trial-{index:03d}",
            case_id="case",
            status=status,
            passed=passed,
            artifact_path=result_path,
            changed_files=(),
        )


if __name__ == "__main__":
    unittest.main()
