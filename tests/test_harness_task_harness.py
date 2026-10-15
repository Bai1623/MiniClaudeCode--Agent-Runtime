"""Tests for Planner Executor Evaluator task harness orchestration."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from miniclaudecode.harness.artifacts import ArtifactStore
from miniclaudecode.harness.budget import RunBudget
from miniclaudecode.harness.evaluator import EvaluationCheck, EvaluationReport
from miniclaudecode.harness.executor import ExecutionResult
from miniclaudecode.harness.planner import Planner, TaskSpec
from miniclaudecode.harness.task_harness import HarnessRunResult, TaskHarness, TaskRunResult
from miniclaudecode.memory import MemoryStore


class FakeExecutor:
    def __init__(self) -> None:
        self.feedbacks: list[str] = []
        self.trace_dirs: list[str] = []
        self.task_ids: list[str] = []

    def set_trace_dir(self, trace_dir):
        self.trace_dirs.append(trace_dir)

    def execute_task(self, store, artifacts, task, feedback=""):
        self.feedbacks.append(feedback)
        self.task_ids.append(task.id)
        store.append_event(artifacts, {"type": "task_started", "task_id": task.id})
        result = ExecutionResult(task_id=task.id, prompt="prompt", response="done")
        store.append_event(artifacts, result.to_event())
        return result


class TracedExecutor(FakeExecutor):
    def execute_task(self, store, artifacts, task, feedback=""):
        result = super().execute_task(store, artifacts, task, feedback)
        with artifacts.model_calls_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps({"input_tokens": 1, "output_tokens": 1}) + "\n")
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
    def test_budget_stops_later_independent_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            executor = TracedExecutor()
            result = TaskHarness(
                store=store, planner=Planner(), executor=executor,
                evaluator=FakeEvaluator(["passed"]), budget=RunBudget(max_api_calls=1),
            ).run(
                request="build", goal="build", tasks=[{"title": "first"}, {"title": "second"}],
            )
            budget = json.loads(result.artifacts.budget_path.read_text(encoding="utf-8"))

        self.assertEqual([item.status for item in result.task_results], ["passed", "budget_exhausted"])
        self.assertEqual(executor.task_ids, ["task-001"])
        self.assertEqual(budget["status"], "exhausted")
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
        self.assertIn({"type": "run_finished", "status": "passed"}, events)
        self.assertEqual(events[-1]["to"], "succeeded")
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

    def test_failed_dependency_blocks_downstream_tasks_but_not_independent_work(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            executor = FakeExecutor()
            evaluator = FakeEvaluator(["failed", "passed"])
            harness = TaskHarness(
                store=store,
                planner=Planner(),
                executor=executor,
                evaluator=evaluator,
                max_repair_rounds=0,
            )
            result = harness.run(
                request="build dependency graph",
                goal="Build dependency graph",
                tasks=[
                    {"id": "core", "title": "Build core"},
                    {"id": "api", "title": "Build API", "depends_on": ["core"]},
                    {"id": "ui", "title": "Build UI", "depends_on": ["api"]},
                    {"id": "docs", "title": "Write docs"},
                ],
            )
            events = [
                json.loads(line)
                for line in result.artifacts.events_path.read_text(encoding="utf-8").splitlines()
            ]
            blocked_report = json.loads(
                (result.artifacts.evaluator_reports_dir / "api.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result.status, "failed")
        self.assertEqual(
            [task_result.status for task_result in result.task_results],
            ["failed", "blocked", "blocked", "passed"],
        )
        self.assertEqual(executor.task_ids, ["core", "docs"])
        self.assertEqual(evaluator.calls, 2)
        self.assertEqual(blocked_report["checks"][0]["metadata"]["blocked_by"], ["core"])
        self.assertIn(
            {"type": "task_blocked", "task_id": "api", "blocked_by": ["core"]},
            events,
        )

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
        self.assertEqual(events[-2]["type"], "memory_written")
        self.assertEqual(events[-1]["to"], "succeeded")

    def test_resume_restarts_only_the_interrupted_task(self):
        class InterruptingExecutor(FakeExecutor):
            def execute_task(self, store, artifacts, task, feedback=""):
                if task.id == "task-002":
                    raise RuntimeError("simulated interruption")
                return super().execute_task(store, artifacts, task, feedback)

        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            interrupted = TaskHarness(
                store=store,
                planner=Planner(),
                executor=InterruptingExecutor(),
                evaluator=FakeEvaluator(["passed"]),
            )
            with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                interrupted.run(
                    request="build two tasks",
                    goal="Build two tasks",
                    tasks=[
                        {"title": "First test"},
                        {
                            "title": "Second test",
                            "acceptance": ["targeted check passes"],
                            "test_commands": [["{python}", "-m", "unittest", "tests.test_config"]],
                        },
                    ],
                )

            artifacts = store.list_runs()[0]
            state = store.read_state(artifacts)
            self.assertEqual(state["status"], "executing")
            self.assertEqual(state["next_task_index"], 1)
            self.assertEqual(state["completed_task_ids"], ["task-001"])

            resumed = TaskHarness(
                store=store,
                planner=Planner(),
                executor=FakeExecutor(),
                evaluator=FakeEvaluator(["passed"]),
            ).resume(artifacts.run_id)
            events = [
                json.loads(line)
                for line in artifacts.events_path.read_text(encoding="utf-8").splitlines()
            ]

            self.assertEqual(resumed.status, "passed")
            self.assertEqual([result.task.id for result in resumed.task_results], ["task-001", "task-002"])
            self.assertEqual(
                resumed.plan.tasks[1].test_commands,
                [["{python}", "-m", "unittest", "tests.test_config"]],
            )
            self.assertIn({"type": "run_resumed", "run_id": artifacts.run_id, "next_task_index": 1}, events)
            self.assertEqual(store.read_state(artifacts)["status"], "succeeded")

    def test_resume_restores_blocked_dependency_results(self):
        class InterruptingIndependentExecutor(FakeExecutor):
            def execute_task(self, store, artifacts, task, feedback=""):
                if task.id == "docs":
                    raise RuntimeError("simulated interruption after blocked task")
                return super().execute_task(store, artifacts, task, feedback)

        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            interrupted = TaskHarness(
                store=store,
                planner=Planner(),
                executor=InterruptingIndependentExecutor(),
                evaluator=FakeEvaluator(["failed"]),
                max_repair_rounds=0,
            )
            with self.assertRaisesRegex(RuntimeError, "after blocked task"):
                interrupted.run(
                    request="build dependency graph",
                    goal="Build dependency graph",
                    tasks=[
                        {"id": "core", "title": "Build core"},
                        {"id": "api", "title": "Build API", "depends_on": ["core"]},
                        {"id": "docs", "title": "Write docs"},
                    ],
                )

            artifacts = store.list_runs()[0]
            self.assertEqual(store.read_state(artifacts)["completed_task_ids"], ["core", "api"])
            resumed_executor = FakeExecutor()
            resumed = TaskHarness(
                store=store,
                planner=Planner(),
                executor=resumed_executor,
                evaluator=FakeEvaluator(["passed"]),
                max_repair_rounds=0,
            ).resume(artifacts.run_id)

        self.assertEqual(
            [task_result.status for task_result in resumed.task_results],
            ["failed", "blocked", "passed"],
        )
        self.assertEqual(resumed_executor.task_ids, ["docs"])


if __name__ == "__main__":
    unittest.main()
