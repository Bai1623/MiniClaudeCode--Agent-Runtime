"""Tests for final harness report generation."""

from __future__ import annotations

import tempfile
import unittest

from miniclaudecode.harness.artifacts import ArtifactStore
from miniclaudecode.harness.evaluator import EvaluationCheck, EvaluationReport
from miniclaudecode.harness.executor import ExecutionResult
from miniclaudecode.harness.planner import Planner, TaskSpec
from miniclaudecode.harness.report import FinalReportGenerator
from miniclaudecode.harness.task_harness import HarnessRunResult, TaskRunResult
from miniclaudecode.git_workflow.diff_summary import DiffSummary, FileChange
from miniclaudecode.git_workflow.test_runner import TestRunResult
from miniclaudecode.git_workflow.workflow import GitWorkflowReport
from miniclaudecode.git_workflow.worktree import WorktreeStatus


class TestFinalReportGenerator(unittest.TestCase):
    def make_result(self, store: ArtifactStore):
        artifacts = store.create_run()
        task = TaskSpec(
            id="task-001",
            title="Add evaluator",
            acceptance=["run tests"],
        )
        plan = Planner().build_plan("Build harness", [task])
        task_result = TaskRunResult(
            task=task,
            executions=[
                ExecutionResult(
                    task_id="task-001",
                    prompt="prompt",
                    response="done",
                )
            ],
            evaluations=[
                EvaluationReport(
                    task_id="task-001",
                    status="passed",
                    checks=[
                        EvaluationCheck(
                            name="unit_tests",
                            status="passed",
                            message="tests ok",
                        )
                    ],
                )
            ],
        )
        return HarnessRunResult(
            artifacts=artifacts,
            plan=plan,
            task_results=[task_result],
        )

    def test_render_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            result = self.make_result(store)
            report = FinalReportGenerator().render(result)

        self.assertIn("# Harness Run Report", report)
        self.assertIn("Status: passed", report)
        self.assertIn("Goal: Build harness", report)
        self.assertIn("task-001: Add evaluator", report)
        self.assertIn("unit_tests: passed - tests ok", report)

    def test_write_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            result = self.make_result(store)
            report = FinalReportGenerator().write(store, result)
            saved = result.artifacts.final_report_path.read_text(encoding="utf-8")

        self.assertEqual(saved, report)

    def test_render_report_with_git_workflow_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            result = self.make_result(store)
            git_report = GitWorkflowReport(
                status=WorktreeStatus(
                    branch="master",
                    changed_files=["miniclaudecode/cli.py"],
                    untracked_files=[],
                    staged_files=[],
                    is_dirty=True,
                ),
                diff_summary=DiffSummary(
                    files=[FileChange("miniclaudecode/cli.py", "modified", 3, 1)],
                    total_additions=3,
                    total_deletions=1,
                ),
                test_result=TestRunResult(
                    command=["python", "-m", "unittest", "discover"],
                    returncode=0,
                    duration_ms=10,
                    stdout="OK",
                    stderr="",
                ),
                commit_message="Update implementation",
            )

            report = FinalReportGenerator().render(result, git_report=git_report)

        self.assertIn("## Git Workflow", report)
        self.assertIn("## Git Workflow Report", report)
        self.assertIn("Branch: master", report)
        self.assertIn("Update implementation", report)


if __name__ == "__main__":
    unittest.main()
