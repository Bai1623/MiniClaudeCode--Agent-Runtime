"""Tests for harness artifact path objects."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from miniclaudecode.harness.artifacts import ArtifactStore, RunArtifacts


class TestRunArtifacts(unittest.TestCase):
    def test_paths_are_derived_from_root(self):
        artifacts = RunArtifacts(run_id="run-1", root=Path("runs") / "run-1")

        self.assertEqual(artifacts.request_path, Path("runs") / "run-1" / "request.md")
        self.assertEqual(artifacts.spec_path, Path("runs") / "run-1" / "spec.md")
        self.assertEqual(artifacts.plan_path, Path("runs") / "run-1" / "plan.json")
        self.assertEqual(artifacts.events_path, Path("runs") / "run-1" / "events.jsonl")
        self.assertEqual(artifacts.final_report_path, Path("runs") / "run-1" / "final_report.md")
        self.assertEqual(artifacts.tasks_dir, Path("runs") / "run-1" / "tasks")
        self.assertEqual(
            artifacts.evaluator_reports_dir,
            Path("runs") / "run-1" / "evaluator_reports",
        )
        self.assertEqual(artifacts.traces_dir, Path("runs") / "run-1" / "traces")


class TestArtifactStore(unittest.TestCase):
    def test_create_run_creates_expected_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            artifacts = store.create_run()

            self.assertEqual(artifacts.root.name, artifacts.run_id)
            self.assertTrue(artifacts.root.is_dir())
            self.assertTrue(artifacts.tasks_dir.is_dir())
            self.assertTrue(artifacts.evaluator_reports_dir.is_dir())
            self.assertTrue(artifacts.traces_dir.is_dir())

    def test_run_id_is_timestamp_plus_short_uuid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = ArtifactStore(base_dir=tmpdir).create_run()

        parts = artifacts.run_id.split("-")
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[0]), 8)
        self.assertEqual(len(parts[1]), 6)
        self.assertEqual(len(parts[2]), 6)
        self.assertTrue(parts[0].isdigit())
        self.assertTrue(parts[1].isdigit())

    def test_get_run_returns_artifacts_for_existing_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            created = store.create_run()
            loaded = store.get_run(created.run_id)

            self.assertEqual(loaded.run_id, created.run_id)
            self.assertEqual(loaded.root, created.root)

    def test_list_runs_returns_directories_newest_name_first(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "20260101-010101-aaaaaa").mkdir()
            (base / "20260102-010101-bbbbbb").mkdir()
            (base / "not-a-run.txt").write_text("ignore")

            runs = ArtifactStore(base_dir=base).list_runs()

        self.assertEqual(
            [run.run_id for run in runs],
            ["20260102-010101-bbbbbb", "20260101-010101-aaaaaa"],
        )

    def test_list_runs_returns_empty_when_base_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runs = ArtifactStore(base_dir=Path(tmpdir) / "missing").list_runs()

        self.assertEqual(runs, [])

    def test_write_request(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            artifacts = store.create_run()
            path = store.write_request(artifacts, "build session persistence")

            self.assertEqual(path, artifacts.request_path)
            self.assertEqual(path.read_text(encoding="utf-8"), "build session persistence")

    def test_write_spec(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            artifacts = store.create_run()
            path = store.write_spec(artifacts, "session persistence spec")

            self.assertEqual(path, artifacts.spec_path)
            self.assertEqual(path.read_text(encoding="utf-8"), "session persistence spec")

    def test_write_and_read_plan(self):
        plan = {
            "goal": "implement session persistence",
            "tasks": [
                {
                    "id": "task-001",
                    "title": "Add SessionStore",
                    "acceptance": ["save messages", "load messages"],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            artifacts = store.create_run()
            path = store.write_plan(artifacts, plan)
            loaded = store.read_plan(artifacts)

            self.assertEqual(path, artifacts.plan_path)
            self.assertEqual(loaded, plan)


if __name__ == "__main__":
    unittest.main()
