"""Planner executor evaluator orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field

from .artifacts import ArtifactStore, RunArtifacts
from .evaluator import EvaluationReport, Evaluator
from .executor import ExecutionResult, Executor
from .planner import Plan, Planner, TaskSpec


@dataclass(frozen=True)
class TaskRunResult:
    task: TaskSpec
    executions: list[ExecutionResult]
    evaluations: list[EvaluationReport]

    @property
    def status(self) -> str:
        if not self.evaluations:
            return "failed"
        return self.evaluations[-1].status


@dataclass(frozen=True)
class HarnessRunResult:
    artifacts: RunArtifacts
    plan: Plan
    task_results: list[TaskRunResult] = field(default_factory=list)

    @property
    def status(self) -> str:
        if all(result.status == "passed" for result in self.task_results):
            return "passed"
        return "failed"


class TaskHarness:
    """Runs a deterministic Planner Executor Evaluator workflow."""

    def __init__(
        self,
        *,
        store: ArtifactStore,
        planner: Planner,
        executor: Executor,
        evaluator: Evaluator,
        max_repair_rounds: int = 1,
    ) -> None:
        self.store = store
        self.planner = planner
        self.executor = executor
        self.evaluator = evaluator
        self.max_repair_rounds = max(0, max_repair_rounds)

    def run(self, request: str, goal: str, tasks: list[TaskSpec | dict], spec: str = "") -> HarnessRunResult:
        artifacts = self.store.create_run()
        self.store.write_request(artifacts, request)
        self.store.append_event(artifacts, {"type": "run_created", "run_id": artifacts.run_id})
        if hasattr(self.executor, "set_trace_dir"):
            self.executor.set_trace_dir(str(artifacts.traces_dir))

        plan = self.planner.build_plan(goal=goal, tasks=tasks, spec=spec)
        self.planner.write_plan_artifacts(self.store, artifacts, plan)

        task_results = [
            self._run_task(artifacts, task)
            for task in plan.tasks
        ]

        status = "passed" if all(result.status == "passed" for result in task_results) else "failed"
        self.store.append_event(artifacts, {"type": "run_finished", "status": status})
        return HarnessRunResult(artifacts=artifacts, plan=plan, task_results=task_results)

    def _run_task(self, artifacts: RunArtifacts, task: TaskSpec) -> TaskRunResult:
        executions: list[ExecutionResult] = []
        evaluations: list[EvaluationReport] = []
        feedback = ""

        for attempt in range(self.max_repair_rounds + 1):
            if attempt > 0:
                self.store.append_event(artifacts, {"type": "repair_started", "task_id": task.id})

            executions.append(self.executor.execute_task(self.store, artifacts, task, feedback=feedback))
            evaluation = self.evaluator.evaluate_task(self.store, artifacts, task)
            evaluations.append(evaluation)

            if evaluation.status == "passed":
                self.store.append_event(artifacts, {"type": "task_finished", "task_id": task.id, "status": "passed"})
                break

            self.store.append_event(artifacts, {"type": "evaluation_failed", "task_id": task.id})
            feedback = self._format_feedback(evaluation)
        else:
            self.store.append_event(artifacts, {"type": "task_finished", "task_id": task.id, "status": "failed"})

        return TaskRunResult(task=task, executions=executions, evaluations=evaluations)

    @staticmethod
    def _format_feedback(report: EvaluationReport) -> str:
        failed = [
            f"{check.name}: {check.message}"
            for check in report.checks
            if check.status != "passed"
        ]
        return "\n".join(failed) or "Evaluation failed without detailed feedback."
