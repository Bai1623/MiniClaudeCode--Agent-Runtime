"""Configurable deterministic graders for harness tasks."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

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
    acceptance_criteria: list[str] = field(default_factory=list)
    test_commands: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "task_id": self.task_id,
            "status": self.status,
            "acceptance_criteria": list(self.acceptance_criteria),
            "test_commands": [list(command) for command in self.test_commands],
            "checks": [check.to_dict() for check in self.checks],
        }


CommandRunner = Callable[[list[str], Path], CommandResult]


@dataclass(frozen=True)
class GraderContext:
    task: TaskSpec
    project_dir: Path
    runner: CommandRunner


class HarnessGrader(Protocol):
    """A named deterministic task check registered with the harness evaluator."""

    @property
    def name(self) -> str:
        ...

    def grade(self, context: GraderContext) -> EvaluationCheck:
        ...


@dataclass(frozen=True)
class CommandGrader:
    name: str
    command: tuple[str, ...]
    empty_message: str = "Command completed without output."

    def grade(self, context: GraderContext) -> EvaluationCheck:
        command = [sys.executable if part == "{python}" else part for part in self.command]
        result = context.runner(command, context.project_dir)
        status = "passed" if result.returncode == 0 else "failed"
        message = result.stdout.strip() or result.stderr.strip() or self.empty_message
        return EvaluationCheck(
            name=self.name,
            status=status,
            message=message,
            metadata={"command": result.command, "returncode": result.returncode},
        )


class GraderRegistry:
    """Maps stable grader names to independently replaceable implementations."""

    def __init__(self) -> None:
        self._graders: dict[str, HarnessGrader] = {}

    @classmethod
    def default(cls) -> GraderRegistry:
        registry = cls()
        registry.register(
            CommandGrader(
                name="unit_tests",
                command=("{python}", "-m", "unittest", "discover"),
            )
        )
        registry.register(
            CommandGrader(
                name="py_compile",
                command=("{python}", "-m", "compileall", "-q", "miniclaudecode", "tests"),
            )
        )
        registry.register(
            CommandGrader(
                name="git_diff_stat",
                command=("git", "diff", "--stat"),
                empty_message="No diff output.",
            )
        )
        return registry

    def register(self, grader: HarnessGrader) -> None:
        if not grader.name:
            raise ValueError("Harness grader name must not be empty.")
        if grader.name in self._graders:
            raise ValueError(f"Harness grader already registered: {grader.name}")
        self._graders[grader.name] = grader

    def grade(self, name: str, context: GraderContext) -> EvaluationCheck:
        grader = self._graders.get(name)
        if grader is None:
            available = ", ".join(self.names()) or "none"
            raise ValueError(f"Unknown harness grader '{name}'. Available graders: {available}.")
        check = grader.grade(context)
        if check.name != name:
            raise ValueError(f"Harness grader '{name}' returned a check named '{check.name}'.")
        return check

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._graders))


DEFAULT_HARNESS_GRADERS = ("unit_tests", "py_compile", "git_diff_stat")


class Evaluator:
    """Runs configured deterministic graders and writes task evaluator reports."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        project_dir: str | Path = ".",
        *,
        registry: GraderRegistry | None = None,
        enabled_graders: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.runner = runner or self._default_runner
        self.project_dir = Path(project_dir)
        self.registry = registry or GraderRegistry.default()
        self.enabled_graders = tuple(
            DEFAULT_HARNESS_GRADERS if enabled_graders is None else enabled_graders
        )
        if not self.enabled_graders:
            raise ValueError("At least one harness grader must be enabled.")
        for name in self.enabled_graders:
            if name not in self.registry.names():
                available = ", ".join(self.registry.names()) or "none"
                raise ValueError(
                    f"Unknown harness grader '{name}'. Available graders: {available}."
                )

    def evaluate_task(
        self,
        store: ArtifactStore,
        artifacts: RunArtifacts,
        task: TaskSpec,
    ) -> EvaluationReport:
        context = GraderContext(task=task, project_dir=self.project_dir, runner=self.runner)
        checks = [self.registry.grade(name, context) for name in self.enabled_graders]
        checks.extend(self._run_task_test_commands(task, context))
        status = "passed" if all(check.status == "passed" for check in checks) else "failed"
        report = EvaluationReport(
            task_id=task.id,
            status=status,
            checks=checks,
            acceptance_criteria=list(task.acceptance),
            test_commands=[list(command) for command in task.test_commands],
        )
        store.write_evaluator_report(artifacts, task.id, report.to_dict())
        return report

    def run_unittest_check(self) -> EvaluationCheck:
        return self._run_registered("unit_tests")

    def run_py_compile_check(self) -> EvaluationCheck:
        return self._run_registered("py_compile")

    def run_git_diff_check(self) -> EvaluationCheck:
        return self._run_registered("git_diff_stat")

    def _run_registered(self, name: str) -> EvaluationCheck:
        context = GraderContext(
            task=TaskSpec(id="manual-check", title=name),
            project_dir=self.project_dir,
            runner=self.runner,
        )
        return self.registry.grade(name, context)

    @staticmethod
    def _run_task_test_commands(
        task: TaskSpec,
        context: GraderContext,
    ) -> list[EvaluationCheck]:
        checks = []
        for index, command in enumerate(task.test_commands, start=1):
            grader = CommandGrader(
                name=f"task_test_{index:03d}",
                command=tuple(command),
            )
            check = grader.grade(context)
            checks.append(
                EvaluationCheck(
                    name=check.name,
                    status=check.status,
                    message=check.message,
                    metadata={
                        **check.metadata,
                        "scope": "task",
                        "acceptance_criteria": list(task.acceptance),
                    },
                )
            )
        return checks

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
