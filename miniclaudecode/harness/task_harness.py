"""Planner executor evaluator orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from miniclaudecode.memory.records import TaskMemory
from miniclaudecode.memory.store import MemoryStore

from .artifacts import ArtifactStore, RunArtifacts
from .budget import BudgetExceededError, BudgetTracker, RunBudget, load_persisted_budget
from .evaluator import EvaluationCheck, EvaluationReport, Evaluator
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
    memory_path: Path | None = None

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
        memory_store: MemoryStore | None = None,
        budget: RunBudget | None = None,
    ) -> None:
        self.store = store
        self.planner = planner
        self.executor = executor
        self.evaluator = evaluator
        self.max_repair_rounds = max(0, max_repair_rounds)
        self.memory_store = memory_store
        self.budget = budget or RunBudget()
        self._budget_tracker: BudgetTracker | None = None

    def run(self, request: str, goal: str, tasks: list[TaskSpec | dict], spec: str = "") -> HarnessRunResult:
        artifacts = self.store.create_run()
        self._budget_tracker = BudgetTracker(artifacts, self.budget)
        self._persist_budget(artifacts, "active")
        self.store.write_request(artifacts, request)
        self.store.append_event(artifacts, {"type": "run_created", "run_id": artifacts.run_id})
        plan = self.planner.build_plan(goal=goal, tasks=tasks, spec=spec)
        self.planner.write_plan_artifacts(self.store, artifacts, plan)
        self._write_state(artifacts, status="created", next_task_index=0, completed_task_ids=[])
        self._transition(artifacts, "planned", next_task_index=0, completed_task_ids=[])
        return self._execute_plan(artifacts, plan, start_index=0, prior_results=[])

    def resume(self, run_id: str) -> HarnessRunResult:
        """Resume an interrupted run from its first unfinished task boundary."""
        artifacts = self.store.get_run(run_id)
        state = self.store.read_state(artifacts)
        if state.get("run_id") != run_id:
            raise ValueError(f"Harness state run_id does not match requested run: {run_id}")
        if state.get("status") in {"succeeded", "failed", "cancelled"}:
            raise ValueError(f"Harness run is already terminal: {state['status']}")
        plan = self._load_plan(artifacts)
        next_task_index = int(state.get("next_task_index", 0))
        if next_task_index < 0 or next_task_index > len(plan.tasks):
            raise ValueError(f"Invalid next_task_index in {artifacts.state_path}")
        completed_ids = [str(task_id) for task_id in state.get("completed_task_ids", [])]
        prior_results = self._load_completed_results(artifacts, plan, completed_ids)
        budget, elapsed = load_persisted_budget(artifacts.budget_path, self.budget)
        self._budget_tracker = BudgetTracker(artifacts, budget, elapsed_base=elapsed)
        self._persist_budget(artifacts, "active")
        self.store.append_event(artifacts, {"type": "run_resumed", "run_id": run_id, "next_task_index": next_task_index})
        return self._execute_plan(artifacts, plan, start_index=next_task_index, prior_results=prior_results)

    def _execute_plan(
        self,
        artifacts: RunArtifacts,
        plan: Plan,
        *,
        start_index: int,
        prior_results: list[TaskRunResult],
    ) -> HarnessRunResult:
        if hasattr(self.executor, "set_trace_dir"):
            self.executor.set_trace_dir(str(artifacts.traces_dir))
        if hasattr(self.executor, "set_budget_guard"):
            self.executor.set_budget_guard(self._require_budget)

        task_results = list(prior_results)
        completed_ids = [result.task.id for result in task_results]
        results_by_id = {result.task.id: result for result in task_results}
        for index, task in enumerate(plan.tasks[start_index:], start=start_index):
            blocked_by = [
                dependency
                for dependency in task.depends_on
                if results_by_id[dependency].status != "passed"
            ]
            if blocked_by:
                task_result = self._block_task(artifacts, task, blocked_by)
            else:
                try:
                    self._require_budget("model_call")
                    self._transition(
                        artifacts,
                        "executing",
                        next_task_index=index,
                        completed_task_ids=completed_ids,
                        task_id=task.id,
                    )
                    task_result = self._run_task(artifacts, task)
                except BudgetExceededError as error:
                    task_result = self._budget_exhausted_task(artifacts, task, error)
            task_results.append(task_result)
            results_by_id[task.id] = task_result
            completed_ids.append(task.id)
            self._persist_budget(
                artifacts,
                "exhausted" if task_result.status == "budget_exhausted" else "active",
            )
            self._transition(
                artifacts,
                "planned",
                next_task_index=index + 1,
                completed_task_ids=completed_ids,
                task_id=task.id,
            )

        status = "passed" if all(result.status == "passed" for result in task_results) else "failed"
        self._persist_budget(
            artifacts,
            "completed" if status == "passed" else "exhausted" if any(
                result.status == "budget_exhausted" for result in task_results
            ) else "completed",
        )
        self.store.append_event(artifacts, {"type": "run_finished", "status": status})
        memory_path = self._write_task_memory(artifacts, plan, task_results, status)
        self._transition(
            artifacts,
            "succeeded" if status == "passed" else "failed",
            next_task_index=len(plan.tasks),
            completed_task_ids=completed_ids,
        )
        return HarnessRunResult(
            artifacts=artifacts,
            plan=plan,
            task_results=task_results,
            memory_path=memory_path,
        )

    def _run_task(self, artifacts: RunArtifacts, task: TaskSpec) -> TaskRunResult:
        executions: list[ExecutionResult] = []
        evaluations: list[EvaluationReport] = []
        feedback = ""

        for attempt in range(self.max_repair_rounds + 1):
            try:
                if attempt > 0:
                    self.store.append_event(artifacts, {"type": "repair_started", "task_id": task.id})
                self._require_budget("model_call")
                executions.append(self.executor.execute_task(self.store, artifacts, task, feedback=feedback))
                self._require_budget()
                evaluation = self.evaluator.evaluate_task(self.store, artifacts, task)
                evaluations.append(evaluation)
                self._require_budget()
            except BudgetExceededError as error:
                return self._budget_exhausted_task(
                    artifacts, task, error, executions=executions, evaluations=evaluations
                )

            if evaluation.status == "passed":
                self.store.append_event(artifacts, {"type": "task_finished", "task_id": task.id, "status": "passed"})
                break

            self.store.append_event(artifacts, {"type": "evaluation_failed", "task_id": task.id})
            feedback = self._format_feedback(evaluation)
        else:
            self.store.append_event(artifacts, {"type": "task_finished", "task_id": task.id, "status": "failed"})

        return TaskRunResult(task=task, executions=executions, evaluations=evaluations)

    def _require_budget(self, operation: str = "usage") -> None:
        if self._budget_tracker is None:
            raise RuntimeError("Harness budget tracker has not been initialized.")
        self._budget_tracker.check(operation)

    def _persist_budget(self, artifacts: RunArtifacts, status: str) -> None:
        if self._budget_tracker is not None:
            self.store.write_budget(artifacts, self._budget_tracker.snapshot(status=status))

    def _budget_exhausted_task(
        self,
        artifacts: RunArtifacts,
        task: TaskSpec,
        error: BudgetExceededError,
        *,
        executions: list[ExecutionResult] | None = None,
        evaluations: list[EvaluationReport] | None = None,
    ) -> TaskRunResult:
        report = EvaluationReport(
            task_id=task.id,
            status="budget_exhausted",
            checks=[EvaluationCheck(
                name="run_budget",
                status="failed",
                message=str(error),
                metadata={"violations": list(error.violations), "usage": error.usage.to_dict()},
            )],
            acceptance_criteria=list(task.acceptance),
            test_commands=[list(command) for command in task.test_commands],
        )
        self.store.write_evaluator_report(artifacts, task.id, report.to_dict())
        self.store.append_event(artifacts, {
            "type": "budget_exhausted", "task_id": task.id,
            "violations": list(error.violations),
        })
        return TaskRunResult(
            task=task,
            executions=executions or [],
            evaluations=[*(evaluations or []), report],
        )

    def _block_task(
        self,
        artifacts: RunArtifacts,
        task: TaskSpec,
        blocked_by: list[str],
    ) -> TaskRunResult:
        message = f"Blocked by unsuccessful dependencies: {', '.join(blocked_by)}."
        report = EvaluationReport(
            task_id=task.id,
            status="blocked",
            checks=[
                EvaluationCheck(
                    name="dependencies",
                    status="blocked",
                    message=message,
                    metadata={"blocked_by": list(blocked_by)},
                )
            ],
            acceptance_criteria=list(task.acceptance),
            test_commands=[list(command) for command in task.test_commands],
        )
        self.store.write_evaluator_report(artifacts, task.id, report.to_dict())
        self.store.append_event(
            artifacts,
            {
                "type": "task_blocked",
                "task_id": task.id,
                "blocked_by": list(blocked_by),
            },
        )
        return TaskRunResult(task=task, executions=[], evaluations=[report])

    def _transition(
        self,
        artifacts: RunArtifacts,
        status: str,
        *,
        next_task_index: int,
        completed_task_ids: list[str],
        task_id: str | None = None,
    ) -> None:
        previous = self.store.read_state(artifacts).get("status")
        self._write_state(
            artifacts,
            status=status,
            next_task_index=next_task_index,
            completed_task_ids=completed_task_ids,
        )
        event: dict[str, Any] = {
            "type": "state_transition",
            "from": previous,
            "to": status,
            "next_task_index": next_task_index,
        }
        if task_id is not None:
            event["task_id"] = task_id
        self.store.append_event(artifacts, event)

    def _write_state(
        self,
        artifacts: RunArtifacts,
        *,
        status: str,
        next_task_index: int,
        completed_task_ids: list[str],
    ) -> None:
        self.store.write_state(
            artifacts,
            {
                "schema_version": 1,
                "run_id": artifacts.run_id,
                "status": status,
                "next_task_index": next_task_index,
                "completed_task_ids": completed_task_ids,
                "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )

    def _load_plan(self, artifacts: RunArtifacts) -> Plan:
        raw_plan = self.store.read_plan(artifacts)
        tasks = raw_plan.get("tasks")
        if not isinstance(tasks, list) or "goal" not in raw_plan:
            raise ValueError(f"Invalid plan artifact: {artifacts.plan_path}")
        return self.planner.build_plan(str(raw_plan["goal"]), tasks, spec=str(raw_plan.get("spec", "")))

    def _load_completed_results(
        self,
        artifacts: RunArtifacts,
        plan: Plan,
        completed_ids: list[str],
    ) -> list[TaskRunResult]:
        tasks_by_id = {task.id: task for task in plan.tasks}
        results: list[TaskRunResult] = []
        for task_id in completed_ids:
            task = tasks_by_id.get(task_id)
            report_path = artifacts.evaluator_reports_dir / f"{task_id}.json"
            if task is None or not report_path.is_file():
                raise ValueError(f"Cannot restore completed task '{task_id}' from artifacts.")
            raw = json.loads(report_path.read_text(encoding="utf-8"))
            checks = [
                EvaluationCheck(
                    name=str(check["name"]),
                    status=str(check["status"]),
                    message=str(check.get("message", "")),
                    metadata=dict(check.get("metadata", {})),
                )
                for check in raw.get("checks", [])
            ]
            results.append(TaskRunResult(
                task=task,
                executions=[],
                evaluations=[
                    EvaluationReport(
                        task_id=task_id,
                        status=str(raw["status"]),
                        checks=checks,
                        acceptance_criteria=[
                            str(item) for item in raw.get("acceptance_criteria", task.acceptance)
                        ],
                        test_commands=[
                            [str(part) for part in command]
                            for command in raw.get("test_commands", task.test_commands)
                        ],
                    )
                ],
            ))
        return results

    @staticmethod
    def _format_feedback(report: EvaluationReport) -> str:
        failed = [
            f"{check.name}: {check.message}"
            for check in report.checks
            if check.status != "passed"
        ]
        return "\n".join(failed) or "Evaluation failed without detailed feedback."

    def _write_task_memory(
        self,
        artifacts: RunArtifacts,
        plan: Plan,
        task_results: list[TaskRunResult],
        status: str,
    ) -> Path | None:
        if self.memory_store is None:
            return None

        changed_files = sorted(
            {
                str(artifacts.request_path),
                str(artifacts.plan_path),
                str(artifacts.final_report_path),
                *[
                    str(artifacts.evaluator_reports_dir / f"{result.task.id}.json")
                    for result in task_results
                ],
            }
        )
        tests = sorted(
            {
                check.name
                for result in task_results
                for evaluation in result.evaluations
                for check in evaluation.checks
                if check.status == "passed"
            }
        )
        summary = "; ".join(
            f"{result.task.id} {result.status}: {result.task.title}"
            for result in task_results
        )
        memory = TaskMemory(
            id=f"harness-{artifacts.run_id}",
            goal=plan.goal,
            changed_files=changed_files,
            tests=tests,
            result=status,
            summary=summary or "Harness run completed without task details.",
        )
        path = self.memory_store.write_task_memory(memory)
        self.store.append_event(
            artifacts,
            {
                "type": "memory_written",
                "path": str(path),
            },
        )
        return path
