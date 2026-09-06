"""Tests for versioned offline evaluation case manifests."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from miniclaudecode.evals import EvalCase, EvalCaseValidationError, EvalCatalog


class TestEvalCase(unittest.TestCase):
    def make_values(self):
        return {
            "schema_version": 1,
            "id": "fix-example",
            "task": "Fix the example bug.",
            "fixture": "example",
            "success_criteria": ["tests pass"],
            "graders": [{"kind": "command", "config": {"command": ["python", "-m", "unittest"]}}],
            "budget": {"max_model_calls": 3},
            "tags": ["bug-fix"],
        }

    def test_round_trip_keeps_versioned_contract(self):
        case = EvalCase.from_dict(self.make_values())

        self.assertEqual(case.id, "fix-example")
        self.assertEqual(case.budget.max_model_calls, 3)
        self.assertEqual(EvalCase.from_dict(case.to_dict()), case)

    def test_rejects_unknown_fields(self):
        values = self.make_values()
        values["surprise"] = True

        with self.assertRaisesRegex(EvalCaseValidationError, "Unknown eval case fields"):
            EvalCase.from_dict(values)

    def test_rejects_nonportable_fixture(self):
        values = self.make_values()
        values["fixture"] = "../outside"

        with self.assertRaisesRegex(EvalCaseValidationError, "portable path"):
            EvalCase.from_dict(values)

    def test_rejects_nonpositive_budget_and_duplicate_tags(self):
        values = self.make_values()
        values["budget"] = {"max_tool_calls": 0}
        with self.assertRaisesRegex(EvalCaseValidationError, "positive integer"):
            EvalCase.from_dict(values)

        values = self.make_values()
        values["tags"] = ["smoke", "smoke"]
        with self.assertRaisesRegex(EvalCaseValidationError, "duplicates"):
            EvalCase.from_dict(values)


class TestEvalCatalog(unittest.TestCase):
    def test_repository_catalog_loads_portable_fixture(self):
        root = Path(__file__).parents[1] / "evals"
        cases = EvalCatalog(root).load()

        self.assertIn("fix-calculator-add", [case.id for case in cases])
        case = next(case for case in cases if case.id == "fix-calculator-add")
        self.assertTrue(case.resolve_fixture(root / "cases").is_dir())

    def test_bug_fix_fixture_starts_with_a_reproducible_failure(self):
        root = Path(__file__).parents[1] / "evals"
        case = next(case for case in EvalCatalog(root).load() if case.id == "fix-calculator-add")

        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "discover"],
            cwd=case.resolve_fixture(root / "cases"),
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("FAILED", completed.stderr)

    def test_catalog_rejects_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cases_dir = root / "cases"
            fixture_dir = root / "fixtures" / "example"
            cases_dir.mkdir(parents=True)
            fixture_dir.mkdir(parents=True)
            values = TestEvalCase().make_values()
            for name in ("one.json", "two.json"):
                (cases_dir / name).write_text(json.dumps(values), encoding="utf-8")

            with self.assertRaisesRegex(EvalCaseValidationError, "Duplicate"):
                EvalCatalog(root).load()


if __name__ == "__main__":
    unittest.main()
