"""Tests for reproducible evaluation experiment manifests."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from miniclaudecode.config import Config
from miniclaudecode.evals import EvalCatalog, ExperimentManifestBuilder


class TestExperimentManifest(unittest.TestCase):
    def setUp(self):
        self.eval_root = Path(__file__).parents[1] / "evals"
        self.case = next(
            case
            for case in EvalCatalog(self.eval_root).load()
            if case.id == "fix-calculator-add"
        )
        self.now = datetime(2026, 9, 23, 4, 5, 6, tzinfo=timezone.utc)

    def test_captures_git_config_runtime_case_and_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = Path(tmpdir)
            self._initialize_repository(repository)
            config = Config(model="test-model", max_turns=7, permission_mode="auto")
            builder = ExperimentManifestBuilder(
                config=config,
                project_root=repository,
                clock=lambda: self.now,
            )

            manifest = builder.build(self.case, trial_count=3)

            (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")
            dirty_manifest = builder.build(self.case, trial_count=3)

        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["created_at"], "2026-09-23T04:05:06Z")
        self.assertTrue(manifest["source"]["git"]["available"])
        self.assertEqual(len(manifest["source"]["git"]["commit_sha"]), 40)
        self.assertFalse(manifest["source"]["git"]["dirty"])
        self.assertTrue(dirty_manifest["source"]["git"]["dirty"])
        self.assertEqual(manifest["agent"]["model"], "test-model")
        self.assertEqual(len(manifest["configuration"]["sha256"]), 64)
        self.assertEqual(
            manifest["configuration"]["values"]["safety"]["workspace_root"],
            "<isolated-trial-workspace>",
        )
        self.assertEqual(manifest["evaluation"]["case_schema_version"], 1)
        self.assertEqual(manifest["evaluation"]["requested_trials"], 3)
        self.assertEqual(manifest["evaluation"]["budget"]["timeout_seconds"], 120)
        self.assertTrue(manifest["runtime"]["python_version"])
        self.assertTrue(manifest["runtime"]["system"])

    def test_config_fingerprint_is_stable_and_changes_with_effective_config(self):
        first = ExperimentManifestBuilder(
            config=Config(model="same-model", max_turns=5),
            clock=lambda: self.now,
        ).build(self.case, trial_count=1)
        second = ExperimentManifestBuilder(
            config=Config(model="same-model", max_turns=5, workspace_root="random-path"),
            clock=lambda: self.now,
        ).build(self.case, trial_count=1)
        changed = ExperimentManifestBuilder(
            config=Config(model="same-model", max_turns=6),
            clock=lambda: self.now,
        ).build(self.case, trial_count=1)

        self.assertEqual(first["configuration"]["sha256"], second["configuration"]["sha256"])
        self.assertNotEqual(first["configuration"]["sha256"], changed["configuration"]["sha256"])

    def test_non_git_directory_is_recorded_as_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = ExperimentManifestBuilder(
                project_root=tmpdir,
                clock=lambda: self.now,
            ).build(self.case, trial_count=1)

        self.assertFalse(manifest["source"]["git"]["available"])
        self.assertIsNone(manifest["source"]["git"]["commit_sha"])
        self.assertFalse(manifest["configuration"]["available"])
        self.assertIsNone(manifest["configuration"]["sha256"])

    def _initialize_repository(self, root: Path) -> None:
        (root / "tracked.txt").write_text("baseline\n", encoding="utf-8")
        commands = (
            ["git", "init", "--quiet"],
            ["git", "add", "tracked.txt"],
            [
                "git",
                "-c",
                "user.name=Eval Test",
                "-c",
                "user.email=eval@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "baseline",
            ],
        )
        for command in commands:
            subprocess.run(command, cwd=root, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
