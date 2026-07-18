"""Tests for Planner Executor Evaluator task harness orchestration."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from miniclaudecode.harness.artifacts import ArtifactStore
from miniclaudecode.harness.evaluator import EvaluationCheck, EvaluationReport
from miniclaudecode.harness.executor import ExecutionResult
from miniclaudecode.harness.planner import Planner, TaskSpec
from miniclaudecode.harness.task_harness import HarnessRunResult, TaskHarness, TaskRunResult
from miniclaudecode.memory import MemoryStore


class FakeExecutor:
    def __init__(self) -> None:
        self.feedbacks: list[str] = []
        self.trace_dirs: list[str] = []

    def set_trace_dir(self, trace_dir):
        self.trace_dirs.append(trace_dir)

    def execute_task(self, store, artifacts, task, feedback=""):
        self.feedbacks.append(feedback)
        store.append_event(artifacts, {"type": "task_started", "task_id": task.id})
        result = ExecutionResult(task_id=task.id, prompt="prompt", response="done")
        store.append_event(artifacts, result.to_event())
        return result


class FakeEvaluator:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses
        self.calls = 0

    def evaluate_task(self, store, artifacts, task):
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        report = EvaluationReport(
            task_id=task.id,
            status=status,
            checks=[
                EvaluationCheck(
                    name="unit_tests",
                    status=status,
                    message="ok" if status == "passed" else "tests failed",
                )
            ],
        )
        store.write_evaluator_report(artifacts, task.id, report.to_dict())
        return report


class TestHarnessResults(unittest.TestCase):
    def test_task_run_result_status(self):
        task = TaskSpec(id="task-001", title="Task")
        result = TaskRunResult(
            task=task,
            executions=[],
            evaluations=[EvaluationReport(task_id="task-001", status="passed", checks=[])],
        )

        self.assertEqual(result.status, "passed")

    def test_harness_run_result_status(self):
        task = TaskSpec(id="task-001", title="Task")
        run = HarnessRunResult(
            artifacts=ArtifactStore(base_dir="runs").get_run("run"),
            plan=Planner().build_plan("goal", [task]),
            task_results=[
                TaskRunResult(
                    task=task,
                    executions=[],
                    evaluations=[EvaluationReport(task_id="task-001", status="failed", checks=[])],
                )
            ],
        )

        self.assertEqual(run.status, "failed")


class TestTaskHarness(unittest.TestCase):
    def test_run_passes_single_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            executor = FakeExecutor()
            evaluator = FakeEvaluator(["passed"])
            harness = TaskHarness(
                store=store,
                planner=Planner(),
                executor=executor,
                evaluator=evaluator,
            )
            result = harness.run(
                request="build evaluator",
                goal="Build evaluator",
                spec="Spec",
                tasks=[{"title": "Add evaluator", "acceptance": ["add tests"]}],
            )

            events = [
                json.loads(line)
                for line in result.artifacts.events_path.read_text(encoding="utf-8").splitlines()
            ]
            request_exists = result.artifacts.request_path.exists()
            plan_exists = result.artifacts.plan_path.exists()

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.plan.tasks[0].id, "task-001")
        self.assertTrue(request_exists)
        self.assertTrue(plan_exists)
        self.assertEqual(events[0]["type"], "run_created")
        self.assertEqual(events[-1], {"type": "run_finished", "status": "passed"})
        self.assertEqual(executor.trace_dirs, [str(result.artifacts.traces_dir)])

    def test_run_repairs_failed_task_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            executor = FakeExecutor()
            evaluator = FakeEvaluator(["failed", "passed"])
            harness = TaskHarness(
                store=store,
                planner=Planner(),
                executor=executor,
                evaluator=evaluator,
                max_repair_rounds=1,
            )
            result = harness.run(
                request="build evaluator",
                goal="Build evaluator",
                tasks=[{"title": "Add evaluator", "acceptance": ["add tests"]}],
            )

        self.assertEqual(result.status, "passed")
        self.assertEqual(len(result.task_results[0].executions), 2)
        self.assertEqual(executor.feedbacks[0], "")
        self.assertIn("tests failed", executor.feedbacks[1])

    def test_run_fails_after_repairs_exhausted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            harness = TaskHarness(
                store=store,
                planner=Planner(),
                executor=FakeExecutor(),
                evaluator=FakeEvaluator(["failed", "failed"]),
                max_repair_rounds=1,
            )
            result = harness.run(
                request="build evaluator",
                goal="Build evaluator",
                tasks=[{"title": "Add evaluator", "acceptance": ["add tests"]}],
            )

        self.assertEqual(result.status, "failed")
        self.assertEqual(len(result.task_results[0].evaluations), 2)

    def test_run_writes_task_memory_when_store_is_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_store = ArtifactStore(base_dir=Path(tmpdir) / "runs")
            memory_store = MemoryStore(Path(tmpdir) / "memory")
            harness = TaskHarness(
                store=artifact_store,
                planner=Planner(),
                executor=FakeExecutor(),
                evaluator=FakeEvaluator(["passed"]),
                memory_store=memory_store,
            )
            result = harness.run(
                request="build memory integration",
                goal="Build memory integration",
                tasks=[{"title": "Add memory write", "acceptance": ["add tests"]}],
            )
            events = [
                json.loads(line)
                for line in result.artifacts.events_path.read_text(encoding="utf-8").splitlines()
            ]
            memory_count = len(memory_store.list_task_memories())
            memory_id = memory_store.list_task_memories()[0].id

        self.assertIsNotNone(result.memory_path)
        self.assertEqual(memory_count, 1)
        self.assertEqual(memory_id, f"harness-{result.artifacts.run_id}")
        self.assertEqual(events[-1]["type"], "memory_written")


if __name__ == "__main__":
    unittest.main()
