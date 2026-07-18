"""Final report generation for harness runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from .artifacts import ArtifactStore
from .task_harness import HarnessRunResult

if TYPE_CHECKING:
    from miniclaudecode.git_workflow.workflow import GitWorkflowReport


class FinalReportGenerator:
    """Renders a Markdown report from a completed harness run."""

    def render(self, result: HarnessRunResult, git_report: GitWorkflowReport | None = None) -> str:
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

        lines.extend(_render_audit_trail(result, git_report))

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
        git_report: GitWorkflowReport | None = None,
    ) -> str:
        report = self.render(result, git_report=git_report)
        store.write_final_report(result.artifacts, report)
        return report


def _render_audit_trail(result: HarnessRunResult, git_report: GitWorkflowReport | None) -> list[str]:
    events = _read_jsonl(result.artifacts.events_path)
    traces = _read_trace_events(result.artifacts.traces_dir)
    lines = [
        "## Audit Trail",
        "",
        f"Events recorded: {len(events)}",
        f"Tool calls traced: {len(traces)}",
        "",
    ]

    repair_events = [event for event in events if event.get("type") == "repair_started"]
    evaluation_events = [event for event in events if event.get("type") == "evaluation_failed"]
    task_finished = [event for event in events if event.get("type") == "task_finished"]

    lines.extend([
        "### Run Events",
        "",
        f"Repair rounds: {len(repair_events)}",
        f"Failed evaluations: {len(evaluation_events)}",
        f"Finished tasks: {len(task_finished)}",
        "",
    ])

    if traces:
        lines.extend(["### Tool Calls", ""])
        for trace in traces:
            status = trace.get("status", "unknown")
            name = trace.get("tool_name", "unknown")
            turn = trace.get("turn", "?")
            duration = trace.get("duration_ms", "?")
            output_chars = trace.get("output_chars", "?")
            lines.append(
                f"- turn {turn}: {name} {status}, {duration} ms, {output_chars} output chars"
            )
        lines.append("")
    else:
        lines.extend(["### Tool Calls", "", "No tool traces recorded.", ""])

    lines.extend(["### Evaluations", ""])
    for task_result in result.task_results:
        latest = task_result.evaluations[-1] if task_result.evaluations else None
        if latest is None:
            lines.append(f"- {task_result.task.id}: no evaluation recorded")
            continue
        check_summary = ", ".join(
            f"{check.name}={check.status}" for check in latest.checks
        ) or "no checks"
        lines.append(f"- {task_result.task.id}: {latest.status} ({check_summary})")
    lines.append("")

    if git_report is not None:
        lines.extend([
            "### Git And Tests",
            "",
            f"Changed files: {len(git_report.status.changed_files)}",
            f"Diff: +{git_report.diff_summary.total_additions} -{git_report.diff_summary.total_deletions}",
        ])
        if git_report.test_result is not None:
            test_status = "passed" if git_report.test_result.passed else "failed"
            command = " ".join(git_report.test_result.command)
            lines.append(f"Tests: {test_status} (`{command}`)")
        else:
            lines.append("Tests: not run")
        lines.append("")

    return lines


def _read_trace_events(traces_dir: Path) -> list[dict]:
    events: list[dict] = []
    if not traces_dir.is_dir():
        return events
    for path in sorted(traces_dir.glob("*.jsonl")):
        events.extend(_read_jsonl(path))
    return events


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records
