"""Tests for deterministic harness evaluator checks."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from miniclaudecode.harness.artifacts import ArtifactStore
from miniclaudecode.harness.evaluator import (
    CommandResult,
    EvaluationCheck,
    EvaluationReport,
    Evaluator,
    GraderContext,
    GraderRegistry,
)
from miniclaudecode.harness.planner import TaskSpec


class FakeRunner:
    def __init__(self, results: dict[tuple[str, ...], CommandResult]) -> None:
        self.results = results
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command: list[str], cwd: Path) -> CommandResult:
        self.calls.append((command, cwd))
        return self.results[tuple(command)]


class TaskIdentityGrader:
    name = "task_identity"

    def grade(self, context: GraderContext) -> EvaluationCheck:
        return EvaluationCheck(
            name=self.name,
            status="passed" if context.task.id else "failed",
            metadata={"task_id": context.task.id},
        )


class TestEvaluationModels(unittest.TestCase):
    def test_check_to_dict(self):
        check = EvaluationCheck(
            name="unit_tests",
            status="passed",
            message="ok",
            metadata={"returncode": 0},
        )

        self.assertEqual(check.to_dict(), {
            "name": "unit_tests",
            "status": "passed",
            "message": "ok",
            "metadata": {"returncode": 0},
        })

    def test_report_to_dict(self):
        report = EvaluationReport(
            task_id="task-001",
            status="passed",
            checks=[EvaluationCheck(name="unit_tests", status="passed")],
        )

        self.assertEqual(report.to_dict(), {
            "schema_version": 2,
            "task_id": "task-001",
            "status": "passed",
            "acceptance_criteria": [],
            "test_commands": [],
            "checks": [
                {
                    "name": "unit_tests",
                    "status": "passed",
                    "message": "",
                    "metadata": {},
                }
            ],
        })


class TestEvaluator(unittest.TestCase):
    def make_runner(self, unittest_code: int = 0, compile_code: int = 0, diff_code: int = 0) -> FakeRunner:
        return FakeRunner({
            (sys.executable, "-m", "unittest", "discover"): CommandResult(
                command=[sys.executable, "-m", "unittest", "discover"],
                returncode=unittest_code,
                stdout="tests ok" if unittest_code == 0 else "",
                stderr="" if unittest_code == 0 else "tests failed",
            ),
            (sys.executable, "-m", "compileall", "-q", "miniclaudecode", "tests"): CommandResult(
                command=[sys.executable, "-m", "compileall", "-q", "miniclaudecode", "tests"],
                returncode=compile_code,
                stdout="",
                stderr="" if compile_code == 0 else "compile failed",
            ),
            ("git", "diff", "--stat"): CommandResult(
                command=["git", "diff", "--stat"],
                returncode=diff_code,
                stdout=" README.md | 2 +-" if diff_code == 0 else "",
                stderr="" if diff_code == 0 else "git failed",
            ),
        })

    def test_command_checks_pass(self):
        runner = self.make_runner()
        evaluator = Evaluator(runner=runner, project_dir=".")

        self.assertEqual(evaluator.run_unittest_check().status, "passed")
        self.assertEqual(evaluator.run_py_compile_check().status, "passed")
        self.assertEqual(evaluator.run_git_diff_check().status, "passed")

    def test_command_check_failure(self):
        runner = self.make_runner(unittest_code=1)
        evaluator = Evaluator(runner=runner, project_dir=".")

        check = evaluator.run_unittest_check()

        self.assertEqual(check.status, "failed")
        self.assertEqual(check.metadata["returncode"], 1)
        self.assertIn("tests failed", check.message)

    def test_registry_supports_custom_configured_grader(self):
        registry = GraderRegistry()
        registry.register(TaskIdentityGrader())
        evaluator = Evaluator(
            runner=self.make_runner(),
            registry=registry,
            enabled_graders=["task_identity"],
        )
        task = TaskSpec(id="task-001", title="Add evaluator")

        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            report = evaluator.evaluate_task(store, store.create_run(), task)

        self.assertEqual(report.status, "passed")
        self.assertEqual([check.name for check in report.checks], ["task_identity"])
        self.assertEqual(report.checks[0].metadata["task_id"], "task-001")

    def test_unknown_or_empty_grader_configuration_fails_fast(self):
        with self.assertRaisesRegex(ValueError, "Unknown harness grader"):
            Evaluator(runner=self.make_runner(), enabled_graders=["missing"])
        with self.assertRaisesRegex(ValueError, "At least one harness grader"):
            Evaluator(runner=self.make_runner(), enabled_graders=[])

    def test_evaluate_task_writes_report(self):
        runner = self.make_runner()
        evaluator = Evaluator(runner=runner, project_dir=".")
        task = TaskSpec(
            id="task-001",
            title="Add evaluator",
            acceptance=["add tests"],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            artifacts = store.create_run()
            report = evaluator.evaluate_task(store, artifacts, task)
            report_path = artifacts.evaluator_reports_dir / "task-001.json"
            saved = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(report.status, "passed")
        self.assertEqual(saved["task_id"], "task-001")
        self.assertEqual(saved["status"], "passed")
        self.assertEqual(saved["schema_version"], 2)
        self.assertEqual(saved["acceptance_criteria"], ["add tests"])
        self.assertEqual(saved["test_commands"], [])
        self.assertEqual(len(saved["checks"]), 3)
        self.assertEqual(
            [check["name"] for check in saved["checks"]],
            ["unit_tests", "py_compile", "git_diff_stat"],
        )

    def test_evaluate_task_fails_when_any_check_fails(self):
        runner = self.make_runner(compile_code=1)
        evaluator = Evaluator(runner=runner, project_dir=".")
        task = TaskSpec(
            id="task-001",
            title="Add evaluator",
            acceptance=["add tests"],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            artifacts = store.create_run()
            report = evaluator.evaluate_task(store, artifacts, task)

        self.assertEqual(report.status, "failed")

    def test_evaluate_task_runs_task_specific_test_commands(self):
        runner = self.make_runner()
        task_command = (sys.executable, "-m", "unittest", "tests.test_harness_evaluator")
        runner.results[task_command] = CommandResult(
            command=list(task_command),
            returncode=0,
            stdout="task tests ok",
        )
        evaluator = Evaluator(runner=runner, project_dir=".")
        task = TaskSpec(
            id="task-001",
            title="Add evaluator",
            acceptance=["Evaluator regression passes."],
            test_commands=[["{python}", "-m", "unittest", "tests.test_harness_evaluator"]],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            report = evaluator.evaluate_task(store, store.create_run(), task)

        task_check = report.checks[-1]
        self.assertEqual(task_check.name, "task_test_001")
        self.assertEqual(task_check.status, "passed")
        self.assertEqual(task_check.metadata["scope"], "task")
        self.assertEqual(
            task_check.metadata["acceptance_criteria"],
            ["Evaluator regression passes."],
        )
        self.assertIn((list(task_command), Path(".")), runner.calls)
        self.assertEqual(report.test_commands, [list(task.test_commands[0])])


if __name__ == "__main__":
    unittest.main()
