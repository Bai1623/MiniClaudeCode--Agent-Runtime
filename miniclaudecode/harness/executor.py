"""Task execution wrapper for harness tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .artifacts import ArtifactStore, RunArtifacts
from .planner import TaskSpec


class AgentRunner(Protocol):
    def run(self, user_message: str) -> str:
        ...

    def set_trace_dir(self, trace_dir: str) -> None:
        ...


@dataclass(frozen=True)
class ExecutionResult:
    task_id: str
    prompt: str
    response: str

    def to_event(self) -> dict[str, str]:
        return {
            "type": "task_executed",
            "task_id": self.task_id,
            "response": self.response,
        }


class Executor:
    """Builds task prompts and delegates execution to an AgentLoop-like runner."""

    def __init__(self, runner: AgentRunner) -> None:
        self.runner = runner

    def set_trace_dir(self, trace_dir: str) -> None:
        if hasattr(self.runner, "set_trace_dir"):
            self.runner.set_trace_dir(trace_dir)

    def execute_task(
        self,
        store: ArtifactStore,
        artifacts: RunArtifacts,
        task: TaskSpec,
        feedback: str = "",
    ) -> ExecutionResult:
        prompt = self.build_task_prompt(task, feedback=feedback)
        store.append_event(artifacts, {"type": "task_started", "task_id": task.id})
        response = self.runner.run(prompt)
        result = ExecutionResult(task_id=task.id, prompt=prompt, response=response)
        store.append_event(artifacts, result.to_event())
        return result

    def build_task_prompt(self, task: TaskSpec, feedback: str = "") -> str:
        lines = [
            "You are executing one task from a long-running coding harness.",
            "",
            f"Task ID: {task.id}",
            f"Title: {task.title}",
            "",
            "Acceptance Criteria:",
        ]

        if task.acceptance:
            for index, item in enumerate(task.acceptance, start=1):
                lines.append(f"{index}. {item}")
        else:
            lines.append("No acceptance criteria provided.")

        if task.notes:
            lines.extend([
                "",
                "Implementation Notes:",
                task.notes,
            ])

        if feedback:
            lines.extend([
                "",
                "Evaluator Feedback From Previous Attempt:",
                feedback,
            ])

        lines.extend([
            "",
            "Work only on this task and keep changes scoped to the acceptance criteria.",
        ])
        return "\n".join(lines).rstrip()
