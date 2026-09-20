"""Isolated, reproducible execution of one offline evaluation trial."""

from __future__ import annotations

import json
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
from .metrics import build_batch_metrics
from .models import EvalCase

EVAL_RESULT_SCHEMA_VERSION = 1


class CandidateExecutor(Protocol):
    """Boundary between workspace orchestration and an agent implementation."""

    def execute(
        self,
        case: EvalCase,
        workspace: Path,
        timeout_seconds: int,
        artifact_dir: Path,
    ) -> CandidateExecution:
        ...


class EvaluationAgent(Protocol):
    context: Any

    def set_trace_dir(self, trace_dir: str) -> None:
        ...

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
        artifact_dir: Path,
    ) -> CandidateExecution:
        agent = self.agent_factory(workspace)
        trace_dir = artifact_dir / "traces"
        agent.set_trace_dir(str(trace_dir))
        try:
            result = agent.run_with_result(case.task)
        finally:
            _write_agent_evidence(agent, artifact_dir, trace_dir)
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


@dataclass(frozen=True)
class EvalBatchResult:
    batch_id: str
    case_id: str
    requested_trials: int
    passed_trials: int
    failed_trials: int
    infrastructure_errors: int
    summary_path: Path
    trials: tuple[EvalRunResult, ...]
    metrics: dict[str, Any]

    @property
    def all_passed(self) -> bool:
        return self.passed_trials == self.requested_trials


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
        batch_id: str | None = None,
    ) -> EvalRunResult:
        resolved_trial_id = trial_id or self._new_trial_id()
        trial_dir = self.artifact_store.create_scoped_trial(
            case.id,
            resolved_trial_id,
            batch_id=batch_id,
        )
        started_at = self.clock()
        started = time.monotonic()
        status = "infrastructure_error"
        passed = False
        changed_files: tuple[str, ...] = ()
        execution: dict[str, Any] = {"status": "not_started"}
        grade_report: dict[str, Any] | None = None
        failure: dict[str, str] | None = None
        stage = "workspace_setup"
        fixture: Path | None = None
        candidate: Path | None = None
        candidate_diff = ""

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
                    trial_dir,
                )
                execution = candidate_result.to_dict()
                changed_files = changed_workspace_files(baseline, candidate)
                candidate_diff = _candidate_diff(candidate)
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
            if fixture is not None and candidate is not None and candidate.is_dir():
                try:
                    changed_files = changed_workspace_files(fixture, candidate)
                    candidate_diff = _candidate_diff(candidate)
                except Exception:
                    pass

        self._write_evidence(
            trial_dir=trial_dir,
            case=case,
            execution=execution,
            candidate_diff=candidate_diff,
            grade_report=grade_report,
        )

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
            "artifacts": {
                "manifest": "artifacts.json",
                "transcript": "transcript.jsonl",
                "tool_trajectory": "tool_trajectory.jsonl",
                "candidate_diff": "candidate.diff",
                "grader_results": "grader_results.json",
            },
        }
        artifact_path = self.artifact_store.write_result(trial_dir, payload)
        self.artifact_store.write_index(trial_dir)
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

    def _write_evidence(
        self,
        *,
        trial_dir: Path,
        case: EvalCase,
        execution: dict[str, Any],
        candidate_diff: str,
        grade_report: dict[str, Any] | None,
    ) -> None:
        transcript_path = trial_dir / "transcript.jsonl"
        if not transcript_path.exists():
            transcript = [
                {"schema_version": 1, "index": 0, "role": "user", "content": case.task},
                {
                    "schema_version": 1,
                    "index": 1,
                    "role": "assistant",
                    "content": execution.get("text", ""),
                    "status": execution.get("status"),
                },
            ]
            self.artifact_store.write_jsonl(transcript_path, transcript)
        trajectory_path = trial_dir / "tool_trajectory.jsonl"
        if not trajectory_path.exists():
            self.artifact_store.write_text(trajectory_path, "")
        self.artifact_store.write_text(trial_dir / "candidate.diff", candidate_diff)
        self.artifact_store.write_json(
            trial_dir / "grader_results.json",
            grade_report or {
                "schema_version": 1,
                "case_id": case.id,
                "passed": False,
                "results": [],
            },
        )


class EvalBatchRunner:
    """Run repeated isolated trials and persist a deterministic batch manifest."""

    def __init__(
        self,
        runner: EvalRunner,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.runner = runner
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        case: EvalCase,
        *,
        manifest_dir: str | Path,
        executor_factory: Callable[[], CandidateExecutor],
        trial_count: int,
        batch_id: str | None = None,
    ) -> EvalBatchResult:
        if isinstance(trial_count, bool) or not isinstance(trial_count, int) or trial_count <= 0:
            raise ValueError("trial_count must be a positive integer.")
        resolved_batch_id = batch_id or self._new_batch_id()
        batch_dir = self.runner.artifact_store.create_batch(case.id, resolved_batch_id)
        trials = tuple(
            self.runner.run(
                case,
                manifest_dir=manifest_dir,
                executor=executor_factory(),
                trial_id=f"trial-{index:03d}",
                batch_id=resolved_batch_id,
            )
            for index in range(1, trial_count + 1)
        )
        passed_trials = sum(result.passed for result in trials)
        infrastructure_errors = sum(
            result.status == "infrastructure_error"
            for result in trials
        )
        failed_trials = trial_count - passed_trials - infrastructure_errors
        metrics = build_batch_metrics(trials)
        summary = {
            "schema_version": 1,
            "batch_id": resolved_batch_id,
            "case_id": case.id,
            "requested_trials": trial_count,
            "completed_trials": len(trials),
            "passed_trials": passed_trials,
            "failed_trials": failed_trials,
            "infrastructure_errors": infrastructure_errors,
            "all_passed": passed_trials == trial_count,
            "metrics": metrics,
            "trials": [
                {
                    "index": index,
                    "trial_id": result.trial_id,
                    "status": result.status,
                    "passed": result.passed,
                    "result": result.artifact_path.relative_to(batch_dir).as_posix(),
                }
                for index, result in enumerate(trials, start=1)
            ],
        }
        summary_path = self.runner.artifact_store.write_batch_summary(batch_dir, summary)
        return EvalBatchResult(
            batch_id=resolved_batch_id,
            case_id=case.id,
            requested_trials=trial_count,
            passed_trials=passed_trials,
            failed_trials=failed_trials,
            infrastructure_errors=infrastructure_errors,
            summary_path=summary_path,
            trials=trials,
            metrics=metrics,
        )

    def _new_batch_id(self) -> str:
        timestamp = self.clock().strftime("%Y%m%dT%H%M%S%fZ")
        return f"batch-{timestamp}-{uuid.uuid4().hex[:8]}"


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


def _candidate_diff(workspace: Path) -> str:
    add = subprocess.run(
        ["git", "add", "--intent-to-add", "--all"],
        cwd=workspace,
        capture_output=True,
        text=True,
        shell=False,
    )
    if add.returncode != 0:
        raise RuntimeError(f"Failed to stage candidate paths for diff: {add.stderr.strip()}")
    diff = subprocess.run(
        ["git", "diff", "--binary", "--no-ext-diff", "HEAD"],
        cwd=workspace,
        capture_output=True,
        text=True,
        shell=False,
    )
    if diff.returncode != 0:
        raise RuntimeError(f"Failed to capture candidate diff: {diff.stderr.strip()}")
    return diff.stdout


def _write_agent_evidence(agent: EvaluationAgent, artifact_dir: Path, trace_dir: Path) -> None:
    messages = getattr(getattr(agent, "context", None), "messages", [])
    transcript = [
        {
            "schema_version": 1,
            "index": index,
            "role": str(message.get("role", "unknown")),
            "content": _json_safe(message.get("content")),
        }
        for index, message in enumerate(messages)
        if isinstance(message, dict)
    ]
    _atomic_write_jsonl(artifact_dir / "transcript.jsonl", transcript)

    events: list[dict[str, Any]] = []
    if trace_dir.is_dir():
        for path in sorted(trace_dir.glob("*.jsonl")):
            if path.name == "model_calls.jsonl":
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError as exc:
                        events.append({
                            "schema_version": 1,
                            "status": "error",
                            "error_type": "trace_decode_error",
                            "source": path.name,
                            "line": exc.lineno,
                        })
                        continue
                    if isinstance(value, dict):
                        events.append(value)
    _atomic_write_jsonl(artifact_dir / "tool_trajectory.jsonl", events)


def _atomic_write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
        encoding="utf-8",
    )
    temporary.replace(path)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump())
    return repr(value)
