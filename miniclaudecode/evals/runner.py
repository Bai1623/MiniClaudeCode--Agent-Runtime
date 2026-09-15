"""Isolated, reproducible execution of one offline evaluation trial."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from .artifacts import EvalArtifactStore
from .graders import GradeContext, GraderRegistry, changed_workspace_files
from .models import EvalCase

EVAL_RESULT_SCHEMA_VERSION = 1


class CandidateExecutor(Protocol):
    """Boundary between workspace orchestration and an agent implementation."""

    def execute(
        self,
        case: EvalCase,
        workspace: Path,
        timeout_seconds: int,
    ) -> CandidateExecution:
        ...


class EvaluationAgent(Protocol):
    def run_with_result(self, user_message: str) -> Any:
        ...


@dataclass(frozen=True)
class CandidateExecution:
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": "completed", "text": self.text, "metadata": dict(self.metadata)}


class AgentCandidateExecutor:
    """Adapt an AgentLoop factory to the evaluation executor boundary."""

    def __init__(self, agent_factory: Callable[[Path], EvaluationAgent]) -> None:
        self.agent_factory = agent_factory

    def execute(
        self,
        case: EvalCase,
        workspace: Path,
        timeout_seconds: int,
    ) -> CandidateExecution:
        result = self.agent_factory(workspace).run_with_result(case.task)
        return CandidateExecution(
            text=str(result.text),
            metadata={
                "run_id": str(result.run_id),
                "turns": int(result.turns),
                "reached_max_turns": bool(result.reached_max_turns),
                "timeout_seconds": timeout_seconds,
            },
        )


@dataclass(frozen=True)
class EvalRunResult:
    trial_id: str
    case_id: str
    status: str
    passed: bool
    artifact_path: Path
    changed_files: tuple[str, ...]


class EvalRunner:
    """Copy a fixture into isolation, execute a candidate, grade it, and persist evidence."""

    def __init__(
        self,
        *,
        artifact_store: EvalArtifactStore | None = None,
        grader_registry: GraderRegistry | None = None,
        work_root: str | Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.artifact_store = artifact_store or EvalArtifactStore()
        self.grader_registry = grader_registry or GraderRegistry.default()
        self.work_root = Path(work_root) if work_root is not None else None
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        case: EvalCase,
        *,
        manifest_dir: str | Path,
        executor: CandidateExecutor,
        trial_id: str | None = None,
    ) -> EvalRunResult:
        resolved_trial_id = trial_id or self._new_trial_id()
        trial_dir = self.artifact_store.create_trial(case.id, resolved_trial_id)
        started_at = self.clock()
        started = time.monotonic()
        status = "infrastructure_error"
        passed = False
        changed_files: tuple[str, ...] = ()
        execution: dict[str, Any] = {"status": "not_started"}
        grade_report: dict[str, Any] | None = None
        failure: dict[str, str] | None = None
        stage = "workspace_setup"

        try:
            fixture = case.resolve_fixture(Path(manifest_dir))
            if not fixture.is_dir():
                raise FileNotFoundError(f"Evaluation fixture does not exist: {fixture}")
            with tempfile.TemporaryDirectory(
                prefix=f"miniclaudecode-eval-{case.id}-",
                dir=self.work_root,
            ) as temporary_root:
                root = Path(temporary_root)
                baseline = root / "baseline"
                candidate = root / "candidate"
                shutil.copytree(fixture, baseline)
                shutil.copytree(fixture, candidate)
                _initialize_git_repository(candidate)
                stage = "candidate_execution"
                candidate_result = executor.execute(
                    case,
                    candidate,
                    case.budget.timeout_seconds,
                )
                execution = candidate_result.to_dict()
                changed_files = changed_workspace_files(baseline, candidate)
                stage = "grading"
                report = self.grader_registry.grade(
                    case,
                    GradeContext(
                        baseline_dir=baseline,
                        candidate_dir=candidate,
                        changed_files=changed_files,
                        timeout_seconds=case.budget.timeout_seconds,
                    ),
                )
                grade_report = report.to_dict()
                passed = report.passed
                status = "passed" if passed else "failed"
        except Exception as exc:
            failure = {
                "stage": stage,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
            if stage == "candidate_execution":
                execution = {"status": "error", **failure}

        ended_at = self.clock()
        payload = {
            "schema_version": EVAL_RESULT_SCHEMA_VERSION,
            "trial_id": resolved_trial_id,
            "case_id": case.id,
            "status": status,
            "passed": passed,
            "started_at": _isoformat(started_at),
            "ended_at": _isoformat(ended_at),
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "fixture": case.fixture,
            "workspace_isolated": True,
            "isolation_mode": "temporary_git_repository",
            "changed_files": list(changed_files),
            "execution": execution,
            "grade_report": grade_report,
            "failure": failure,
        }
        artifact_path = self.artifact_store.write_result(trial_dir, payload)
        return EvalRunResult(
            trial_id=resolved_trial_id,
            case_id=case.id,
            status=status,
            passed=passed,
            artifact_path=artifact_path,
            changed_files=changed_files,
        )

    def _new_trial_id(self) -> str:
        timestamp = self.clock().strftime("%Y%m%dT%H%M%S%fZ")
        return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _initialize_git_repository(workspace: Path) -> None:
    commands = (
        ["git", "init", "--quiet"],
        ["git", "add", "--all"],
        [
            "git",
            "-c",
            "user.name=miniClaudeCode Eval",
            "-c",
            "user.email=eval@miniclaudecode.local",
            "commit",
            "--quiet",
            "-m",
            "eval fixture baseline",
        ],
    )
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            shell=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"Failed to initialize isolated Git repository: {detail}")
