"""Tests for uncertainty and backward compatibility in eval comparisons."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from miniclaudecode.evals import compare_eval_batches, render_comparison_markdown


class TestEvalComparison(unittest.TestCase):
    def test_compares_legacy_failure_fields_and_renders_confidence_intervals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            baseline = self._summary(root / "baseline", "baseline", 0.25, 0.75)
            experiment = self._summary(root / "experiment", "experiment", 0.5, 0.5)

            comparison = compare_eval_batches(baseline, experiment)
            markdown = render_comparison_markdown(comparison)

        agent = next(
            metric for metric in comparison["metrics"] if metric["label"] == "Agent failure rate"
        )
        self.assertEqual(agent["baseline"], 0.75)
        self.assertEqual(agent["experiment"], 0.5)
        self.assertEqual(agent["status"], "improved")
        self.assertIn("Baseline 95% Wilson CI: [0.0456, 0.6994]", markdown)
        self.assertIn("Experiment 95% Wilson CI: [0.1500, 0.8500]", markdown)

    def _summary(self, directory: Path, batch_id: str, pass_rate: float, failure_rate: float) -> Path:
        directory.mkdir()
        path = directory / "trials_summary.json"
        path.write_text(
            json.dumps(
                {
                    "batch_id": batch_id,
                    "case_id": "case",
                    "split": "development",
                    "requested_trials": 4,
                    "completed_trials": 4,
                    "metrics": {
                        "sample_size": 4,
                        "pass_metrics": {
                            "pass@1": pass_rate,
                            "pass@1_confidence_interval": {
                                "lower": 0.0456 if batch_id == "baseline" else 0.15,
                                "upper": 0.6994 if batch_id == "baseline" else 0.85,
                            },
                            "pass@k": {"4": pass_rate},
                            "pass^k": {"4": 0.0},
                        },
                        "errors": {
                            "task_failure_rate": failure_rate,
                            "infrastructure_error_rate": 0.0,
                            "grader_failure_rate": failure_rate,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    unittest.main()
