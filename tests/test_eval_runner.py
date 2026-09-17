"""Tests for isolated, durable offline evaluation trials."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from miniclaudecode.evals import (
    AgentCandidateExecutor,
    CandidateExecution,
    EvalArtifactStore,
    EvalCatalog,
    EvalRunner,
)


class FixingExecutor:
    def __init__(self) -> None:
        self.workspaces: list[Path] = []

    def execute(
        self,
        case,
        workspace: Path,
        timeout_seconds: int,
        artifact_dir: Path,
    ) -> CandidateExecution:
        self.workspaces.append(workspace)
        if not (workspace / ".git").is_dir():
            raise AssertionError("candidate workspace must be a Git repository")
        calculator = workspace / "calculator.py"
        calculator.write_text(
            calculator.read_text(encoding="utf-8").replace("return left - right", "return left + right", 1),
            encoding="utf-8",
        )
        return CandidateExecution("fixed", {"timeout_seconds": timeout_seconds})


class FailingExecutor:
    def execute(
        self,
        case,
        workspace: Path,
        timeout_seconds: int,
        artifact_dir: Path,
    ) -> CandidateExecution:
        raise RuntimeError("candidate crashed")


class RecordingAgent:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.context = SimpleNamespace(messages=[])
        self.trace_dir: Path | None = None

    def set_trace_dir(self, trace_dir: str) -> None:
        self.trace_dir = Path(trace_dir)

    def run_with_result(self, task: str):
        calculator = self.workspace / "calculator.py"
        calculator.write_text(
            calculator.read_text(encoding="utf-8").replace(
                "return left - right",
                "return left + right",
                1,
            ),
            encoding="utf-8",
        )
        self.context.messages.extend([
            {"role": "user", "content": task},
            {"role": "assistant", "content": [{"type": "text", "text": "fixed"}]},
        ])
        assert self.trace_dir is not None
        self.trace_dir.mkdir(parents=True)
        (self.trace_dir / "agent-run.jsonl").write_text(
            '{"schema_version":1,"turn":1,"tool_name":"edit_file","status":"ok"}\n',
            encoding="utf-8",
        )
        (self.trace_dir / "model_calls.jsonl").write_text(
            '{"schema_version":1,"turn":1,"model":"test-model"}\n',
            encoding="utf-8",
        )
        return SimpleNamespace(
            text="fixed",
            run_id="agent-run",
            turns=1,
            reached_max_turns=False,
        )


class TestEvalRunner(unittest.TestCase):
    def setUp(self):
        self.eval_root = Path(__file__).parents[1] / "evals"
        self.case = next(
            case
            for case in EvalCatalog(self.eval_root).load()
            if case.id == "fix-calculator-add"
        )
        self.fixture = self.case.resolve_fixture(self.eval_root / "cases")
        self.original = (self.fixture / "calculator.py").read_text(encoding="utf-8")

    def test_runs_candidate_and_graders_in_an_isolated_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = FixingExecutor()
            runner = EvalRunner(
                artifact_store=EvalArtifactStore(Path(tmpdir) / "artifacts"),
                work_root=Path(tmpdir),
            )

            result = runner.run(
                self.case,
                manifest_dir=self.eval_root / "cases",
                executor=executor,
                trial_id="trial-one",
            )
            payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))

            self.assertTrue(result.passed)
            self.assertEqual(result.status, "passed")
            self.assertEqual(result.changed_files, ("calculator.py",))
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["isolation_mode"], "temporary_git_repository")
            self.assertTrue(payload["grade_report"]["passed"])
            self.assertEqual(payload["execution"]["metadata"]["timeout_seconds"], 120)
            self.assertIn("calculator.py", (result.artifact_path.parent / "candidate.diff").read_text(encoding="utf-8"))
            index = json.loads((result.artifact_path.parent / "artifacts.json").read_text(encoding="utf-8"))
            indexed = {entry["path"] for entry in index["artifacts"]}
            self.assertIn("eval_result.json", indexed)
            self.assertIn("grader_results.json", indexed)
            self.assertFalse(executor.workspaces[0].exists())

        self.assertEqual((self.fixture / "calculator.py").read_text(encoding="utf-8"), self.original)

    def test_sequential_trials_do_not_share_candidate_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = FixingExecutor()
            runner = EvalRunner(
                artifact_store=EvalArtifactStore(Path(tmpdir) / "artifacts"),
                work_root=Path(tmpdir),
            )

            first = runner.run(
                self.case,
                manifest_dir=self.eval_root / "cases",
                executor=executor,
                trial_id="trial-one",
            )
            second = runner.run(
                self.case,
                manifest_dir=self.eval_root / "cases",
                executor=executor,
                trial_id="trial-two",
            )

            self.assertTrue(first.passed)
            self.assertTrue(second.passed)
            self.assertNotEqual(first.artifact_path, second.artifact_path)
            self.assertFalse(any(path.exists() for path in executor.workspaces))

    def test_executor_failure_is_persisted_as_infrastructure_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = EvalRunner(
                artifact_store=EvalArtifactStore(Path(tmpdir) / "artifacts"),
                work_root=Path(tmpdir),
            )

            result = runner.run(
                self.case,
                manifest_dir=self.eval_root / "cases",
                executor=FailingExecutor(),
                trial_id="failed-trial",
            )
            payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))

            self.assertFalse(result.passed)
            self.assertEqual(result.status, "infrastructure_error")
            self.assertEqual(payload["execution"]["error_type"], "RuntimeError")
            self.assertIn("candidate crashed", payload["execution"]["error_message"])
            self.assertEqual(payload["failure"]["stage"], "candidate_execution")
            self.assertIsNone(payload["grade_report"])
            self.assertTrue((result.artifact_path.parent / "transcript.jsonl").is_file())
            self.assertTrue((result.artifact_path.parent / "artifacts.json").is_file())

    def test_agent_executor_persists_transcript_trajectory_and_raw_traces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = EvalRunner(
                artifact_store=EvalArtifactStore(Path(tmpdir) / "artifacts"),
                work_root=Path(tmpdir),
            )

            result = runner.run(
                self.case,
                manifest_dir=self.eval_root / "cases",
                executor=AgentCandidateExecutor(RecordingAgent),
                trial_id="agent-trial",
            )
            trial_dir = result.artifact_path.parent
            transcript = [
                json.loads(line)
                for line in (trial_dir / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            trajectory = [
                json.loads(line)
                for line in (trial_dir / "tool_trajectory.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            index = json.loads((trial_dir / "artifacts.json").read_text(encoding="utf-8"))
            indexed = {entry["path"] for entry in index["artifacts"]}

            self.assertTrue(result.passed)
            self.assertEqual([message["role"] for message in transcript], ["user", "assistant"])
            self.assertEqual(trajectory[0]["tool_name"], "edit_file")
            self.assertIn("traces/agent-run.jsonl", indexed)
            self.assertIn("traces/model_calls.jsonl", indexed)

    def test_trial_id_collision_does_not_overwrite_prior_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = EvalRunner(
                artifact_store=EvalArtifactStore(Path(tmpdir) / "artifacts"),
                work_root=Path(tmpdir),
            )
            runner.run(
                self.case,
                manifest_dir=self.eval_root / "cases",
                executor=FixingExecutor(),
                trial_id="same-id",
            )

            with self.assertRaises(FileExistsError):
                runner.run(
                    self.case,
                    manifest_dir=self.eval_root / "cases",
                    executor=FixingExecutor(),
                    trial_id="same-id",
                )

    def test_trial_id_cannot_escape_artifact_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = EvalRunner(
                artifact_store=EvalArtifactStore(Path(tmpdir) / "artifacts"),
                work_root=Path(tmpdir),
            )

            with self.assertRaisesRegex(ValueError, "trial_id"):
                runner.run(
                    self.case,
                    manifest_dir=self.eval_root / "cases",
                    executor=FixingExecutor(),
                    trial_id="../escape",
                )


if __name__ == "__main__":
    unittest.main()
