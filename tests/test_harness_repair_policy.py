"""Tests for error-type-aware repair routing."""

from __future__ import annotations

import unittest

from miniclaudecode.harness.evaluator import EvaluationCheck, EvaluationReport
from miniclaudecode.harness.repair_policy import route_repair


class TestRepairPolicy(unittest.TestCase):
    def test_allows_known_recoverable_errors(self):
        decision = route_repair(
            EvaluationReport(
                task_id="task-001", status="failed",
                checks=[EvaluationCheck("tool", "failed", metadata={"error_type": "validation_error"})],
            ),
            ["timeout_error"],
        )

        self.assertTrue(decision.should_retry)
        self.assertEqual(decision.error_types, ("timeout_error", "validation_error"))

    def test_blocks_nonrecoverable_errors(self):
        decision = route_repair(
            EvaluationReport(
                task_id="task-001", status="failed",
                checks=[EvaluationCheck("tool", "failed", metadata={"error_type": "permission_denied"})],
            ),
        )

        self.assertFalse(decision.should_retry)
        self.assertEqual(decision.reason, "contains_nonrecoverable_or_unknown_error")
