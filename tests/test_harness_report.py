"""Tests for final harness report generation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from miniclaudecode.git_workflow.diff_summary import DiffSummary, FileChange
from miniclaudecode.git_workflow.test_runner import TestRunResult
from miniclaudecode.git_workflow.workflow import GitWorkflowReport
from miniclaudecode.git_workflow.worktree import WorktreeStatus
from miniclaudecode.harness.artifacts import ArtifactStore
from miniclaudecode.harness.evaluator import EvaluationCheck, EvaluationReport
from miniclaudecode.harness.executor import ExecutionResult
from miniclaudecode.harness.planner import Planner, TaskSpec
from miniclaudecode.harness.report import FinalReportGenerator
from miniclaudecode.harness.task_harness import HarnessRunResult, TaskRunResult


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
            store.append_event(result.artifacts, {"type": "repair_started", "task_id": "task-001"})
            trace_path = result.artifacts.traces_dir / "trace.jsonl"
            trace_path.write_text(
                json.dumps({
                    "run_id": "run",
                    "turn": 1,
                    "tool_name": "grep",
                    "status": "ok",
                    "duration_ms": 12,
                    "output_chars": 20,
                }) + "\n",
                encoding="utf-8",
            )
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
        self.assertIn("## Audit Trail", report)
        self.assertIn("Tool calls traced: 1", report)
        self.assertIn("Repair rounds: 1", report)
        self.assertIn("turn 1: grep ok, 12 ms, 20 output chars", report)
        self.assertIn("Tests: passed", report)
        self.assertIn("## Git Workflow Report", report)
        self.assertIn("Branch: master", report)
        self.assertIn("Update implementation", report)

    def test_render_report_with_memory_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            result = self.make_result(store)
            result = HarnessRunResult(
                artifacts=result.artifacts,
                plan=result.plan,
                task_results=result.task_results,
                memory_path=Path(tmpdir) / "memory" / "tasks" / "harness.md",
            )

            report = FinalReportGenerator().render(result)

        self.assertIn("Memory:", report)
        self.assertIn("harness.md", report)


if __name__ == "__main__":
    unittest.main()
