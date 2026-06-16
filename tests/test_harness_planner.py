"""Tests for deterministic harness planning primitives."""

from __future__ import annotations

import tempfile
import unittest

from miniclaudecode.harness.artifacts import ArtifactStore
from miniclaudecode.harness.planner import Plan, Planner, TaskSpec


class TestTaskSpec(unittest.TestCase):
    def test_to_dict_omits_empty_notes(self):
        task = TaskSpec(
            id="task-001",
            title="Add planner",
            acceptance=["plan is structured"],
        )

        self.assertEqual(task.to_dict(), {
            "id": "task-001",
            "title": "Add planner",
            "acceptance": ["plan is structured"],
        })

    def test_to_dict_includes_notes(self):
        task = TaskSpec(
            id="task-001",
            title="Add planner",
            acceptance=[],
            notes="Keep it deterministic.",
        )

        self.assertEqual(task.to_dict()["notes"], "Keep it deterministic.")


class TestPlan(unittest.TestCase):
    def test_to_dict(self):
        plan = Plan(
            goal="Build harness planner",
            spec="Planner spec",
            tasks=[
                TaskSpec(
                    id="task-001",
                    title="Add planner",
                    acceptance=["writes plan.json"],
                )
            ],
        )

        self.assertEqual(plan.to_dict(), {
            "goal": "Build harness planner",
            "spec": "Planner spec",
            "tasks": [
                {
                    "id": "task-001",
                    "title": "Add planner",
                    "acceptance": ["writes plan.json"],
                }
            ],
        })


class TestPlanner(unittest.TestCase):
    def setUp(self):
        self.planner = Planner()

    def test_build_plan_assigns_task_ids(self):
        plan = self.planner.build_plan(
            goal="Build evaluator",
            tasks=[
                {"title": "Add evaluator", "acceptance": ["runs tests"]},
                {"title": "Write tests", "acceptance": ["covers failure"]},
            ],
        )

        self.assertEqual([task.id for task in plan.tasks], ["task-001", "task-002"])

    def test_build_plan_preserves_explicit_task_id(self):
        plan = self.planner.build_plan(
            goal="Build evaluator",
            tasks=[
                {"id": "custom-task", "title": "Add evaluator"},
            ],
        )

        self.assertEqual(plan.tasks[0].id, "custom-task")

    def test_render_task_markdown(self):
        task = TaskSpec(
            id="task-001",
            title="Add planner",
            acceptance=["writes plan.json", "writes task markdown"],
            notes="Use ArtifactStore.",
        )

        markdown = self.planner.render_task_markdown(task)

        self.assertIn("# task-001", markdown)
        self.assertIn("## Title", markdown)
        self.assertIn("Add planner", markdown)
        self.assertIn("1. writes plan.json", markdown)
        self.assertIn("2. writes task markdown", markdown)
        self.assertIn("## Notes", markdown)
        self.assertTrue(markdown.endswith("\n"))

    def test_write_plan_artifacts(self):
        plan = self.planner.build_plan(
            goal="Build planner",
            spec="Planner should create task contracts.",
            tasks=[
                {
                    "title": "Add planner",
                    "acceptance": ["plan.json exists", "task markdown exists"],
                }
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            artifacts = store.create_run()
            self.planner.write_plan_artifacts(store, artifacts, plan)

            loaded_plan = store.read_plan(artifacts)
            task_path = artifacts.tasks_dir / "task-001.md"

            self.assertEqual(artifacts.spec_path.read_text(encoding="utf-8"), plan.spec)
            self.assertEqual(loaded_plan, plan.to_dict())
            self.assertTrue(task_path.exists())
            self.assertIn("Add planner", task_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
