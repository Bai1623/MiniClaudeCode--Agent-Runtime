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
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "acceptance": list(self.acceptance),
        }
        if self.notes:
            data["notes"] = self.notes
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
        notes = str(task.get("notes", ""))
        return TaskSpec(
            id=task_id,
            title=title,
            acceptance=acceptance,
            notes=notes,
        )
