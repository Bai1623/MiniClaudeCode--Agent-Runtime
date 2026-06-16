"""Tests for harness task executor."""

from __future__ import annotations

import json
import tempfile
import unittest

from miniclaudecode.harness.artifacts import ArtifactStore
from miniclaudecode.harness.executor import ExecutionResult, Executor
from miniclaudecode.harness.planner import TaskSpec


class FakeRunner:
    def __init__(self, response: str = "done") -> None:
        self.response = response
        self.prompts: list[str] = []

    def run(self, user_message: str) -> str:
        self.prompts.append(user_message)
        return self.response


class TestExecutionResult(unittest.TestCase):
    def test_to_event(self):
        result = ExecutionResult(
            task_id="task-001",
            prompt="prompt",
            response="done",
        )

        self.assertEqual(result.to_event(), {
            "type": "task_executed",
            "task_id": "task-001",
            "response": "done",
        })


class TestExecutor(unittest.TestCase):
    def test_build_task_prompt(self):
        executor = Executor(runner=FakeRunner())
        task = TaskSpec(
            id="task-001",
            title="Add evaluator",
            acceptance=["run unit tests", "write report"],
            notes="Keep deterministic.",
        )

        prompt = executor.build_task_prompt(task, feedback="compile failed")

        self.assertIn("Task ID: task-001", prompt)
        self.assertIn("Title: Add evaluator", prompt)
        self.assertIn("1. run unit tests", prompt)
        self.assertIn("2. write report", prompt)
        self.assertIn("Keep deterministic.", prompt)
        self.assertIn("compile failed", prompt)

    def test_execute_task_calls_runner_and_records_events(self):
        runner = FakeRunner(response="task complete")
        executor = Executor(runner=runner)
        task = TaskSpec(
            id="task-001",
            title="Add executor",
            acceptance=["call runner"],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            artifacts = store.create_run()
            result = executor.execute_task(store, artifacts, task)
            events = [
                json.loads(line)
                for line in artifacts.events_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(result.task_id, "task-001")
        self.assertEqual(result.response, "task complete")
        self.assertEqual(len(runner.prompts), 1)
        self.assertEqual(events[0], {"type": "task_started", "task_id": "task-001"})
        self.assertEqual(events[1], {
            "type": "task_executed",
            "task_id": "task-001",
            "response": "task complete",
        })


if __name__ == "__main__":
    unittest.main()
