"""Deterministic evaluation checks for harness tasks."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Any

from .artifacts import ArtifactStore, RunArtifacts
from .planner import TaskSpec


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class EvaluationCheck:
    name: str
    status: str
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EvaluationReport:
    task_id: str
    status: str
    checks: list[EvaluationCheck]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "checks": [check.to_dict() for check in self.checks],
        }


CommandRunner = Callable[[list[str], Path], CommandResult]


class Evaluator:
    """Runs deterministic checks and writes task evaluator reports."""

    def __init__(self, runner: CommandRunner | None = None, project_dir: str | Path = ".") -> None:
        self.runner = runner or self._default_runner
        self.project_dir = Path(project_dir)

    def evaluate_task(
        self,
        store: ArtifactStore,
        artifacts: RunArtifacts,
        task: TaskSpec,
    ) -> EvaluationReport:
        checks = [
            self.run_unittest_check(),
            self.run_py_compile_check(),
            self.run_git_diff_check(),
            self.check_task_mentions_tests(task),
        ]
        status = "passed" if all(check.status == "passed" for check in checks) else "failed"
        report = EvaluationReport(task_id=task.id, status=status, checks=checks)
        store.write_evaluator_report(artifacts, task.id, report.to_dict())
        return report

    def run_unittest_check(self) -> EvaluationCheck:
        result = self.runner(["python", "-m", "unittest", "discover"], self.project_dir)
        return self._command_check("unit_tests", result)

    def run_py_compile_check(self) -> EvaluationCheck:
        result = self.runner(["python", "-m", "compileall", "-q", "miniclaudecode", "tests"], self.project_dir)
        return self._command_check("py_compile", result)

    def run_git_diff_check(self) -> EvaluationCheck:
        result = self.runner(["git", "diff", "--stat"], self.project_dir)
        status = "passed" if result.returncode == 0 else "failed"
        message = result.stdout.strip() or result.stderr.strip() or "No diff output."
        return EvaluationCheck(
            name="git_diff_stat",
            status=status,
            message=message,
            metadata={
                "command": result.command,
                "returncode": result.returncode,
            },
        )

    def check_task_mentions_tests(self, task: TaskSpec) -> EvaluationCheck:
        text = " ".join([task.title, task.notes, " ".join(task.acceptance)]).lower()
        mentions_tests = "test" in text or "测试" in text
        return EvaluationCheck(
            name="test_coverage_intent",
            status="passed" if mentions_tests else "failed",
            message="Task mentions tests." if mentions_tests else "Task does not mention tests.",
        )

    @staticmethod
    def _command_check(name: str, result: CommandResult) -> EvaluationCheck:
        status = "passed" if result.returncode == 0 else "failed"
        message = result.stdout.strip() or result.stderr.strip() or "Command completed without output."
        return EvaluationCheck(
            name=name,
            status=status,
            message=message,
            metadata={
                "command": result.command,
                "returncode": result.returncode,
            },
        )

    @staticmethod
    def _default_runner(command: list[str], cwd: Path) -> CommandResult:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return CommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
