"""Task execution wrapper for harness tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

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
    run_id: str | None = None

    def to_event(self) -> dict[str, str]:
        event = {
            "type": "task_executed",
            "task_id": self.task_id,
            "response": self.response,
        }
        if self.run_id is not None:
            event["run_id"] = self.run_id
        return event


class Executor:
    """Builds task prompts and delegates execution to an AgentLoop-like runner."""

    def __init__(self, runner: AgentRunner) -> None:
        self.runner = runner

    def set_trace_dir(self, trace_dir: str) -> None:
        if hasattr(self.runner, "set_trace_dir"):
            self.runner.set_trace_dir(trace_dir)

    def set_budget_guard(self, guard: Callable[[str], Any] | None) -> None:
        if hasattr(self.runner, "set_budget_guard"):
            self.runner.set_budget_guard(guard)

    def execute_task(
        self,
        store: ArtifactStore,
        artifacts: RunArtifacts,
        task: TaskSpec,
        feedback: str = "",
    ) -> ExecutionResult:
        prompt = self.build_task_prompt(task, feedback=feedback)
        store.append_event(artifacts, {"type": "task_started", "task_id": task.id})
        run_with_result = getattr(self.runner, "run_with_result", None)
        if callable(run_with_result):
            agent_result = run_with_result(prompt)
            response = str(agent_result.text)
            run_id = str(agent_result.run_id)
        else:
            response = self.runner.run(prompt)
            run_id = None
        result = ExecutionResult(task_id=task.id, prompt=prompt, response=response, run_id=run_id)
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

        if task.test_commands:
            lines.extend(["", "Task-Specific Test Commands:"])
            for command in task.test_commands:
                lines.append(f"- {' '.join(command)}")

        if task.depends_on:
            lines.extend(["", "Satisfied Task Dependencies:"])
            for task_id in task.depends_on:
                lines.append(f"- {task_id}")

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
