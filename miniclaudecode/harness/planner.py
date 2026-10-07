"""Deterministic planning primitives for long-running harness tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .artifacts import ArtifactStore, RunArtifacts


@dataclass(frozen=True)
class TaskSpec:
    """A single executable task contract."""

    id: str
    title: str
    acceptance: list[str] = field(default_factory=list)
    test_commands: list[list[str]] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Task id must not be empty.")
        if not self.title.strip():
            raise ValueError("Task title must not be empty.")
        if any(not isinstance(item, str) or not item.strip() for item in self.acceptance):
            raise ValueError("Task acceptance criteria must not contain empty values.")
        for command in self.test_commands:
            if not command or any(not isinstance(part, str) or not part for part in command):
                raise ValueError("Task test commands must be non-empty lists of strings.")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "acceptance": list(self.acceptance),
        }
        if self.notes:
            data["notes"] = self.notes
        if self.test_commands:
            data["test_commands"] = [list(command) for command in self.test_commands]
        return data


@dataclass(frozen=True)
class Plan:
    """A structured plan for a harness run."""

    goal: str
    tasks: list[TaskSpec]
    spec: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "goal": self.goal,
            "tasks": [task.to_dict() for task in self.tasks],
        }
        if self.spec:
            data["spec"] = self.spec
        return data


class Planner:
    """Builds and writes deterministic task plans."""

    def build_plan(self, goal: str, tasks: list[TaskSpec | dict[str, Any]], spec: str = "") -> Plan:
        task_specs = [
            self._coerce_task(task, index=index)
            for index, task in enumerate(tasks, start=1)
        ]
        return Plan(goal=goal, tasks=task_specs, spec=spec)

    def render_task_markdown(self, task: TaskSpec) -> str:
        lines = [
            f"# {task.id}",
            "",
            "## Title",
            "",
            task.title,
            "",
            "## Acceptance",
            "",
        ]

        if task.acceptance:
            for index, item in enumerate(task.acceptance, start=1):
                lines.append(f"{index}. {item}")
        else:
            lines.append("No acceptance criteria provided.")

        if task.test_commands:
            lines.extend(["", "## Test Commands", ""])
            for command in task.test_commands:
                lines.append(f"- `{' '.join(command)}`")

        if task.notes:
            lines.extend([
                "",
                "## Notes",
                "",
                task.notes,
            ])

        return "\n".join(lines).rstrip() + "\n"

    def write_plan_artifacts(
        self,
        store: ArtifactStore,
        artifacts: RunArtifacts,
        plan: Plan,
    ) -> None:
        if plan.spec:
            store.write_spec(artifacts, plan.spec)
        store.write_plan(artifacts, plan.to_dict())
        for task in plan.tasks:
            store.write_task(artifacts, task.id, self.render_task_markdown(task))

    @staticmethod
    def _coerce_task(task: TaskSpec | dict[str, Any], index: int) -> TaskSpec:
        if isinstance(task, TaskSpec):
            return task

        task_id = str(task.get("id") or f"task-{index:03d}")
        title = str(task["title"])
        acceptance = [str(item) for item in task.get("acceptance", [])]
        test_commands = _coerce_test_commands(task.get("test_commands", []))
        notes = str(task.get("notes", ""))
        return TaskSpec(
            id=task_id,
            title=title,
            acceptance=acceptance,
            test_commands=test_commands,
            notes=notes,
        )


def _coerce_test_commands(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        raise ValueError("Task test_commands must be a list of command argument lists.")
    commands: list[list[str]] = []
    for command in value:
        if not isinstance(command, list):
            raise ValueError("Each task test command must be a list of strings.")
        commands.append(list(command))
    return commands
