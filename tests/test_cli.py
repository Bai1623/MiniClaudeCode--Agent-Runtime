"""Tests for CLI harness options."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO

from miniclaudecode.cli import build_parser, default_harness_tasks, list_harness_runs, run_harness
from miniclaudecode.harness.artifacts import ArtifactStore


class TestCliHarnessOptions(unittest.TestCase):
    def test_parser_accepts_harness_options(self):
        parser = build_parser()
        args = parser.parse_args([
            "--run-harness",
            "--harness-task",
            "Task one",
            "--harness-task",
            "Task two",
            "--max-repair-rounds",
            "2",
            "Build feature",
        ])

        self.assertTrue(args.run_harness)
        self.assertEqual(args.harness_task, ["Task one", "Task two"])
        self.assertEqual(args.max_repair_rounds, 2)
        self.assertEqual(args.prompt, "Build feature")

    def test_default_harness_tasks_uses_prompt_when_no_task_titles(self):
        tasks = default_harness_tasks("Build feature", None)

        self.assertEqual(tasks[0]["title"], "Build feature")
        self.assertIn("Run or update relevant tests.", tasks[0]["acceptance"])

    def test_default_harness_tasks_uses_explicit_titles(self):
        tasks = default_harness_tasks("Build feature", ["Task one", "Task two"])

        self.assertEqual([task["title"] for task in tasks], ["Task one", "Task two"])

    def test_list_harness_runs_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = StringIO()
            list_harness_runs(ArtifactStore(base_dir=tmpdir), output=output)

        self.assertIn("No harness runs found.", output.getvalue())

    def test_list_harness_runs_outputs_created_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            artifacts = store.create_run()
            output = StringIO()
            list_harness_runs(store, output=output)

        self.assertIn("Harness runs:", output.getvalue())
        self.assertIn(artifacts.run_id, output.getvalue())

    def test_run_harness_requires_prompt(self):
        args = build_parser().parse_args(["--run-harness"])

        with redirect_stderr(StringIO()):
            self.assertEqual(run_harness(args), 2)


if __name__ == "__main__":
    unittest.main()
