"""Tests for the deterministic parallel-tool ablation."""

from __future__ import annotations

import tempfile
import unittest

from miniclaudecode.evals.parallel_ablation import (
    run_parallel_read_only_ablation,
    write_parallel_read_only_ablation,
)


class TestParallelReadOnlyAblation(unittest.TestCase):
    def test_reports_all_requested_metrics_and_writes_artifacts(self):
        report = run_parallel_read_only_ablation(trials=2, calls_per_trial=3, delay_seconds=0.01)

        self.assertEqual(report["modes"]["sequential"]["success_rate"], 1.0)
        self.assertEqual(report["modes"]["parallel_read_only"]["mean_tokens"], 0)
        self.assertEqual(report["modes"]["parallel_read_only"]["tool_error_rate"], 0.0)
        self.assertGreater(report["comparison"]["latency_speedup"], 1.2)
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path, markdown_path = write_parallel_read_only_ablation(report, tmpdir)
            self.assertTrue(json_path.is_file())
            self.assertIn("Latency speedup", markdown_path.read_text(encoding="utf-8"))
