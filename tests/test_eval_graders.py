"""Tests for deterministic offline evaluation graders."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from miniclaudecode.evals import (
    EvalCase,
    EvalCaseValidationError,
    EvalCatalog,
    GradeContext,
    GraderRegistry,
)


class TestEvalGraders(unittest.TestCase):
    def setUp(self):
        self.eval_root = Path(__file__).parents[1] / "evals"
        self.case = next(
            case for case in EvalCatalog(self.eval_root).load()
            if case.id == "fix-calculator-add"
        )
        self.baseline = self.case.resolve_fixture(self.eval_root / "cases")

    def test_all_graders_pass_for_scoped_bug_fix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            candidate = Path(tmpdir) / "candidate"
            shutil.copytree(self.baseline, candidate)
            (candidate / "calculator.py").write_text(
                "def add(left: int, right: int) -> int:\n"
                "    return left + right\n\n"
                "def subtract(left: int, right: int) -> int:\n"
                "    return left - right\n",
                encoding="utf-8",
            )

            report = GraderRegistry.default().grade(
                self.case,
                GradeContext(
                    baseline_dir=self.baseline,
                    candidate_dir=candidate,
                    changed_files=("calculator.py",),
                ),
            )

        self.assertTrue(report.passed)
        self.assertEqual(
            [result.grader for result in report.results],
            ["no_op", "fail_to_pass", "pass_to_pass", "expected_changes", "forbidden_changes"],
        )
        self.assertTrue(all(result.passed for result in report.results))
        self.assertEqual(report.to_dict()["schema_version"], 1)

    def test_graders_explain_regressions_and_scope_violations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            candidate = Path(tmpdir) / "candidate"
            shutil.copytree(self.baseline, candidate)
            (candidate / "calculator.py").write_text(
                "def add(left: int, right: int) -> int:\n"
                "    return left + right\n\n"
                "def subtract(left: int, right: int) -> int:\n"
                "    return left + right\n",
                encoding="utf-8",
            )

            report = GraderRegistry.default().grade(
                self.case,
                GradeContext(
                    baseline_dir=self.baseline,
                    candidate_dir=candidate,
                    changed_files=("calculator.py", "test_calculator.py"),
                ),
            )

        results = {result.grader: result for result in report.results}
        self.assertFalse(report.passed)
        self.assertFalse(results["pass_to_pass"].passed)
        self.assertFalse(results["expected_changes"].passed)
        self.assertFalse(results["forbidden_changes"].passed)
        self.assertEqual(results["forbidden_changes"].metadata["violations"], ["test_calculator.py"])

    def test_fail_to_pass_rejects_an_unfixed_candidate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            candidate = Path(tmpdir) / "candidate"
            shutil.copytree(self.baseline, candidate)

            report = GraderRegistry.default().grade(
                self.case,
                GradeContext(self.baseline, candidate, ("calculator.py",)),
            )

        result = next(result for result in report.results if result.grader == "fail_to_pass")
        self.assertFalse(result.passed)
        self.assertNotEqual(result.metadata["candidate_returncode"], 0)

    def test_no_op_rejects_unchanged_candidate_and_ignores_generated_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            candidate = Path(tmpdir) / "candidate"
            shutil.copytree(self.baseline, candidate)
            cache_dir = candidate / "__pycache__"
            cache_dir.mkdir(exist_ok=True)
            (cache_dir / "calculator.pyc").write_bytes(b"generated")

            report = GraderRegistry.default().grade(
                self.case,
                GradeContext(self.baseline, candidate, ("__pycache__/calculator.pyc",)),
            )

        result = next(result for result in report.results if result.grader == "no_op")
        self.assertFalse(result.passed)
        self.assertEqual(result.metadata["changed_content_files"], [])
        self.assertEqual(
            result.metadata["baseline_fingerprint"],
            result.metadata["candidate_fingerprint"],
        )

    def test_unknown_grader_kind_fails_explicitly(self):
        values = self.case.to_dict()
        values["graders"] = [{"kind": "unknown", "config": {}}]
        case = EvalCase.from_dict(values)

        with self.assertRaisesRegex(EvalCaseValidationError, "Unknown grader kind"):
            GraderRegistry.default().grade(
                case,
                GradeContext(self.baseline, self.baseline, ()),
            )


if __name__ == "__main__":
    unittest.main()
