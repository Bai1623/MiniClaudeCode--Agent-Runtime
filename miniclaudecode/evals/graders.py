"""Deterministic graders for offline coding-agent evaluation results."""

from __future__ import annotations

import fnmatch
import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .models import EvalCase, EvalCaseValidationError, GraderSpec

MAX_GRADE_OUTPUT_CHARS = 4_000
DEFAULT_NO_OP_IGNORES = (
    ".git/**",
    "__pycache__/**",
    "**/__pycache__/**",
    "*.pyc",
    "**/*.pyc",
    "*.pyo",
    "**/*.pyo",
    ".pytest_cache/**",
    ".mypy_cache/**",
    ".ruff_cache/**",
    ".coverage",
)


@dataclass(frozen=True)
class GradeContext:
    baseline_dir: Path
    candidate_dir: Path
    changed_files: tuple[str, ...]
    timeout_seconds: int = 120


@dataclass(frozen=True)
class GradeResult:
    grader: str
    passed: bool
    message: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "grader": self.grader,
            "passed": self.passed,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EvalGradeReport:
    case_id: str
    passed: bool
    results: tuple[GradeResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "case_id": self.case_id,
            "passed": self.passed,
            "results": [result.to_dict() for result in self.results],
        }


class Grader(Protocol):
    def grade(self, spec: GraderSpec, context: GradeContext) -> GradeResult:
        ...


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class _CommandTransitionGrader:
    kind = ""

    def grade(self, spec: GraderSpec, context: GradeContext) -> GradeResult:
        command = _command_from_config(spec)
        baseline = _run_command(command, context.baseline_dir, context.timeout_seconds)
        candidate = _run_command(command, context.candidate_dir, context.timeout_seconds)
        passed = self._passed(baseline.returncode, candidate.returncode)
        return GradeResult(
            grader=self.kind,
            passed=passed,
            message=self._message(passed, baseline.returncode, candidate.returncode),
            metadata={
                "command": command,
                "baseline_returncode": baseline.returncode,
                "candidate_returncode": candidate.returncode,
                "baseline_output": _bounded_output(baseline),
                "candidate_output": _bounded_output(candidate),
            },
        )

    def _passed(self, baseline_returncode: int, candidate_returncode: int) -> bool:
        raise NotImplementedError

    def _message(self, passed: bool, baseline_returncode: int, candidate_returncode: int) -> str:
        state = "passed" if passed else "failed"
        return (
            f"{self.kind} {state}: baseline={baseline_returncode}, "
            f"candidate={candidate_returncode}."
        )


class FailToPassGrader(_CommandTransitionGrader):
    kind = "fail_to_pass"

    def _passed(self, baseline_returncode: int, candidate_returncode: int) -> bool:
        return baseline_returncode != 0 and candidate_returncode == 0


class PassToPassGrader(_CommandTransitionGrader):
    kind = "pass_to_pass"

    def _passed(self, baseline_returncode: int, candidate_returncode: int) -> bool:
        return baseline_returncode == 0 and candidate_returncode == 0


class ExpectedChangesGrader:
    kind = "expected_changes"

    def grade(self, spec: GraderSpec, context: GradeContext) -> GradeResult:
        required = _path_list(spec, "required", required=True)
        allowed = _path_list(spec, "allowed", required=False)
        changed = {_normalize_path(path) for path in context.changed_files}
        missing = sorted(path for path in required if path not in changed)
        unexpected = sorted(path for path in changed if allowed and path not in allowed)
        passed = not missing and not unexpected
        return GradeResult(
            grader=self.kind,
            passed=passed,
            message=(
                "Expected file changes matched."
                if passed
                else f"Missing required changes: {missing}; unexpected changes: {unexpected}."
            ),
            metadata={
                "required": sorted(required),
                "allowed": sorted(allowed),
                "changed_files": sorted(changed),
                "missing": missing,
                "unexpected": unexpected,
            },
        )


class ForbiddenChangesGrader:
    kind = "forbidden_changes"

    def grade(self, spec: GraderSpec, context: GradeContext) -> GradeResult:
        patterns = _path_list(spec, "patterns", required=True)
        changed = {_normalize_path(path) for path in context.changed_files}
        violations = sorted(
            path
            for path in changed
            if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
        )
        return GradeResult(
            grader=self.kind,
            passed=not violations,
            message=(
                "No forbidden paths changed."
                if not violations
                else f"Forbidden paths changed: {violations}."
            ),
            metadata={"patterns": sorted(patterns), "violations": violations},
        )


class NoOpGrader:
    kind = "no_op"

    def grade(self, spec: GraderSpec, context: GradeContext) -> GradeResult:
        configured_ignores = _path_list(spec, "ignore_patterns", required=False)
        ignore_patterns = tuple(sorted({*DEFAULT_NO_OP_IGNORES, *configured_ignores}))
        baseline = _workspace_snapshot(context.baseline_dir, ignore_patterns)
        candidate = _workspace_snapshot(context.candidate_dir, ignore_patterns)
        changed_content_files = sorted(
            path
            for path in baseline.keys() | candidate.keys()
            if baseline.get(path) != candidate.get(path)
        )
        passed = bool(changed_content_files)
        return GradeResult(
            grader=self.kind,
            passed=passed,
            message=(
                f"Candidate contains substantive changes in {len(changed_content_files)} file(s)."
                if passed
                else "Candidate is a no-op after generated and ignored files are excluded."
            ),
            metadata={
                "changed_content_files": changed_content_files,
                "baseline_fingerprint": _snapshot_fingerprint(baseline),
                "candidate_fingerprint": _snapshot_fingerprint(candidate),
                "ignore_patterns": list(ignore_patterns),
            },
        )
class GraderRegistry:
    def __init__(self) -> None:
        self._graders: dict[str, Grader] = {}

    @classmethod
    def default(cls) -> GraderRegistry:
        registry = cls()
        for grader in (
            NoOpGrader(),
            FailToPassGrader(),
            PassToPassGrader(),
            ExpectedChangesGrader(),
            ForbiddenChangesGrader(),
        ):
            registry.register(grader.kind, grader)
        return registry

    def register(self, kind: str, grader: Grader) -> None:
        if kind in self._graders:
            raise ValueError(f"Grader already registered: {kind}")
        self._graders[kind] = grader

    def grade(self, case: EvalCase, context: GradeContext) -> EvalGradeReport:
        results: list[GradeResult] = []
        for spec in case.graders:
            grader = self._graders.get(spec.kind)
            if grader is None:
                raise EvalCaseValidationError(f"Unknown grader kind: {spec.kind}")
            results.append(grader.grade(spec, context))
        return EvalGradeReport(
            case_id=case.id,
            passed=all(result.passed for result in results),
            results=tuple(results),
        )


def _command_from_config(spec: GraderSpec) -> list[str]:
    command = spec.config.get("command")
    if not isinstance(command, list) or not command or not all(
        isinstance(part, str) and part for part in command
    ):
        raise EvalCaseValidationError(f"{spec.kind}.command must be a non-empty list of strings.")
    normalized = list(command)
    if normalized[0] == "{python}":
        normalized[0] = sys.executable
    return normalized


def _run_command(command: list[str], cwd: Path, timeout_seconds: int) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)
    except subprocess.TimeoutExpired as exc:
        return CommandResult(124, str(exc.stdout or ""), str(exc.stderr or "") + "\ncommand timed out")


def _bounded_output(result: CommandResult) -> str:
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if len(output) <= MAX_GRADE_OUTPUT_CHARS:
        return output
    return output[:MAX_GRADE_OUTPUT_CHARS] + "... (truncated)"


def _path_list(spec: GraderSpec, key: str, *, required: bool) -> set[str]:
    values = spec.config.get(key, [])
    if not isinstance(values, list) or (required and not values):
        qualifier = "non-empty " if required else ""
        raise EvalCaseValidationError(f"{spec.kind}.{key} must be a {qualifier}list of paths.")
    if not all(isinstance(value, str) and value for value in values):
        raise EvalCaseValidationError(f"{spec.kind}.{key} must contain only non-empty strings.")
    return {_normalize_path(value) for value in values}


def _normalize_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise EvalCaseValidationError(f"grader path must stay inside the candidate workspace: {value}")
    return path.as_posix()


def _workspace_snapshot(root: Path, ignore_patterns: tuple[str, ...]) -> dict[str, str]:
    if not root.is_dir():
        raise EvalCaseValidationError(f"grader workspace does not exist: {root}")
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatchcase(relative, pattern) for pattern in ignore_patterns):
            continue
        snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _snapshot_fingerprint(snapshot: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path, content_hash in sorted(snapshot.items()):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()
