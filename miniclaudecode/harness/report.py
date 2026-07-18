"""Final report generation for harness runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .artifacts import ArtifactStore
from .task_harness import HarnessRunResult

if TYPE_CHECKING:
    from miniclaudecode.git_workflow.workflow import GitWorkflowReport


class FinalReportGenerator:
    """Renders a Markdown report from a completed harness run."""

    def render(self, result: HarnessRunResult, git_report: "GitWorkflowReport | None" = None) -> str:
        lines = [
            "# Harness Run Report",
            "",
            "## Summary",
            "",
            f"Run ID: {result.artifacts.run_id}",
            f"Status: {result.status}",
            f"Goal: {result.plan.goal}",
            "",
            "## Tasks",
            "",
        ]

        for task_result in result.task_results:
            lines.extend([
                f"### {task_result.task.id}: {task_result.task.title}",
                "",
                f"Status: {task_result.status}",
                f"Executions: {len(task_result.executions)}",
                f"Evaluations: {len(task_result.evaluations)}",
                "",
                "Acceptance:",
                "",
            ])
            if task_result.task.acceptance:
                for index, item in enumerate(task_result.task.acceptance, start=1):
                    lines.append(f"{index}. {item}")
            else:
                lines.append("No acceptance criteria provided.")

            lines.extend(["", "Checks:", ""])
            latest = task_result.evaluations[-1] if task_result.evaluations else None
            if latest is None or not latest.checks:
                lines.append("No evaluator checks recorded.")
            else:
                for check in latest.checks:
                    lines.append(f"- {check.name}: {check.status} - {check.message}")
            lines.append("")

        lines.extend([
            "## Artifacts",
            "",
            f"Request: {result.artifacts.request_path}",
            f"Plan: {result.artifacts.plan_path}",
            f"Events: {result.artifacts.events_path}",
            f"Evaluator Reports: {result.artifacts.evaluator_reports_dir}",
            f"Traces: {result.artifacts.traces_dir}",
        ])
        if result.memory_path is not None:
            lines.append(f"Memory: {result.memory_path}")
        lines.append("")

        if git_report is not None:
            lines.extend([
                "## Git Workflow",
                "",
                git_report.to_markdown(),
                "",
            ])
        return "\n".join(lines).rstrip() + "\n"

    def write(
        self,
        store: ArtifactStore,
        result: HarnessRunResult,
        git_report: "GitWorkflowReport | None" = None,
    ) -> str:
        report = self.render(result, git_report=git_report)
        store.write_final_report(result.artifacts, report)
        return report
