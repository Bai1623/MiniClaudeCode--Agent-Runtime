"""Tests for trace-backed Harness resource budgets."""

from __future__ import annotations

import json
import tempfile
import unittest

from miniclaudecode.harness.artifacts import ArtifactStore
from miniclaudecode.harness.budget import BudgetExceededError, BudgetTracker, RunBudget


class TestBudgetTracker(unittest.TestCase):
    def test_enforces_projected_api_calls_and_records_usage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = ArtifactStore(tmpdir).create_run()
            artifacts.model_calls_path.write_text(
                json.dumps({
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 2,
                    "estimated_cost_usd": 0.01,
                }) + "\n",
                encoding="utf-8",
            )
            (artifacts.traces_dir / "tools.jsonl").write_text("{}\n{}\n", encoding="utf-8")
            tracker = BudgetTracker(artifacts, RunBudget(max_api_calls=1, max_tool_calls=2))

            usage = tracker.check()
            self.assertEqual(usage.total_tokens, 17)
            self.assertEqual(usage.tool_calls, 2)
            with self.assertRaises(BudgetExceededError):
                tracker.check("model_call")
            with self.assertRaises(BudgetExceededError):
                tracker.check("tool_call")

    def test_rejects_invalid_limits(self):
        with self.assertRaises(ValueError):
            RunBudget(max_api_calls=1.5)
        with self.assertRaises(ValueError):
            RunBudget(max_cost_usd=0)
