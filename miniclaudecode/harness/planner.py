"""Deterministic planning primitives for long-running harness tasks."""

from __future__ import annotations

import heapq
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
    depends_on: list[str] = field(default_factory=list)
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
        if any(not isinstance(task_id, str) or not task_id.strip() for task_id in self.depends_on):
            raise ValueError("Task dependencies must contain non-empty task ids.")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError(f"Task '{self.id}' contains duplicate dependencies.")

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
        if self.depends_on:
            data["depends_on"] = list(self.depends_on)
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
        return Plan(goal=goal, tasks=self._validate_and_order(task_specs), spec=spec)

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

        if task.depends_on:
            lines.extend(["", "## Dependencies", ""])
            for task_id in task.depends_on:
                lines.append(f"- `{task_id}`")

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
        depends_on = _coerce_dependencies(task.get("depends_on", []))
        notes = str(task.get("notes", ""))
        return TaskSpec(
            id=task_id,
            title=title,
            acceptance=acceptance,
            test_commands=test_commands,
            depends_on=depends_on,
            notes=notes,
        )

    @staticmethod
    def _validate_and_order(tasks: list[TaskSpec]) -> list[TaskSpec]:
        positions: dict[str, int] = {}
        for index, task in enumerate(tasks):
            if task.id in positions:
                raise ValueError(f"Duplicate harness task id: {task.id}")
            positions[task.id] = index

        dependents: dict[str, list[str]] = {task.id: [] for task in tasks}
        indegree = {task.id: len(task.depends_on) for task in tasks}
        for task in tasks:
            for dependency in task.depends_on:
                if dependency not in positions:
                    raise ValueError(
                        f"Task '{task.id}' depends on unknown task '{dependency}'."
                    )
                if dependency == task.id:
                    raise ValueError(f"Task '{task.id}' cannot depend on itself.")
                dependents[dependency].append(task.id)

        ready = [(positions[task.id], task.id) for task in tasks if indegree[task.id] == 0]
        heapq.heapify(ready)
        ordered_ids: list[str] = []
        while ready:
            _, task_id = heapq.heappop(ready)
            ordered_ids.append(task_id)
            for dependent in dependents[task_id]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(ready, (positions[dependent], dependent))

        if len(ordered_ids) != len(tasks):
            cycle_ids = sorted(task_id for task_id, count in indegree.items() if count > 0)
            raise ValueError(f"Harness task dependency cycle detected: {', '.join(cycle_ids)}")
        tasks_by_id = {task.id: task for task in tasks}
        return [tasks_by_id[task_id] for task_id in ordered_ids]


def _coerce_test_commands(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        raise ValueError("Task test_commands must be a list of command argument lists.")
    commands: list[list[str]] = []
    for command in value:
        if not isinstance(command, list):
            raise ValueError("Each task test command must be a list of strings.")
        commands.append(list(command))
    return commands


def _coerce_dependencies(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("Task depends_on must be a list of task ids.")
    return [str(item) for item in value]
