"""Final report generation for harness runs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .artifacts import ArtifactStore, build_run_summary, read_jsonl
from .task_harness import HarnessRunResult

if TYPE_CHECKING:
    from miniclaudecode.git_workflow.workflow import GitWorkflowReport


class FinalReportGenerator:
    """Renders a Markdown report from a completed harness run."""

    def render(
        self,
        result: HarnessRunResult,
        git_report: GitWorkflowReport | None = None,
        run_summary: dict | None = None,
    ) -> str:
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

        lines.extend(_render_audit_trail(result, git_report, run_summary or build_run_summary(result.artifacts, status=result.status)))

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
        summary = build_run_summary(result.artifacts, status=result.status)
        store.write_run_summary(result.artifacts, summary)
        report = self.render(result, git_report=git_report, run_summary=summary)
        store.write_final_report(result.artifacts, report)
        return report


def _render_audit_trail(
    result: HarnessRunResult,
    git_report: GitWorkflowReport | None,
    summary: dict,
) -> list[str]:
    events = read_jsonl(result.artifacts.events_path)
    traces = _read_trace_events(result.artifacts.traces_dir)
    lines = [
        "## Audit Trail",
        "",
        f"Events recorded: {len(events)}",
        f"Tool calls traced: {len(traces)}",
    ]
    lines.extend(_render_summary_metrics(summary))
    lines.append("")

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
            compression = _format_trace_compression(trace)
            lines.append(f"- turn {turn}: {name} {status}, {duration} ms, {output_chars} output chars{compression}")
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


def _render_summary_metrics(summary: dict) -> list[str]:
    tool = summary["tool"]
    model = summary["model"]
    return [
        f"Compressed tool calls: {tool['compressed_calls']}",
        "Compression strategies: " + ", ".join(
            f"{name}={count}" for name, count in tool["compression_strategies"].items()
        ),
        f"Snippet-truncated calls: {tool['snippet_truncated_calls']}",
        f"Tool latency: P50={tool['p50_duration_ms']} ms, P95={tool['p95_duration_ms']} ms",
        f"Model calls: {model['calls']}",
        f"Model tokens: input={model['input_tokens']}, output={model['output_tokens']}, cache_read={model['cache_read_input_tokens']}",
        f"Estimated model cost (USD): {model['estimated_cost_usd'] if model['estimated_cost_usd'] is not None else 'not configured'}",
    ]


def _format_trace_compression(trace: dict) -> str:
    if not trace.get("compressed"):
        return ""
    strategy = trace.get("compression_strategy") or "unknown"
    return f", compressed={strategy}"


def _read_trace_events(traces_dir: Path) -> list[dict]:
    events: list[dict] = []
    if not traces_dir.is_dir():
        return events
    for path in sorted(traces_dir.glob("*.jsonl")):
        if path.name != "model_calls.jsonl":
            events.extend(read_jsonl(path))
    return events
