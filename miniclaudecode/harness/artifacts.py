"""Artifact paths for long-running harness runs."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from miniclaudecode.runtime.trace_summary import TraceSummary


@dataclass(frozen=True)
class RunArtifacts:
    """Paths for all artifacts produced by a single harness run."""

    run_id: str
    root: Path

    @property
    def request_path(self) -> Path:
        return self.root / "request.md"

    @property
    def spec_path(self) -> Path:
        return self.root / "spec.md"

    @property
    def plan_path(self) -> Path:
        return self.root / "plan.json"

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def final_report_path(self) -> Path:
        return self.root / "final_report.md"

    @property
    def run_summary_path(self) -> Path:
        return self.root / "run_summary.json"

    @property
    def state_path(self) -> Path:
        return self.root / "run_state.json"

    @property
    def model_calls_path(self) -> Path:
        return self.traces_dir / "model_calls.jsonl"

    @property
    def tasks_dir(self) -> Path:
        return self.root / "tasks"

    @property
    def evaluator_reports_dir(self) -> Path:
        return self.root / "evaluator_reports"

    @property
    def traces_dir(self) -> Path:
        return self.root / "traces"


def _new_run_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    return f"{timestamp}-{suffix}"


class ArtifactStore:
    """Creates and locates artifact directories for harness runs."""

    def __init__(self, base_dir: str | Path = ".miniclaudecode/runs") -> None:
        self.base_dir = Path(base_dir)

    def create_run(self) -> RunArtifacts:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        run_id = _new_run_id()
        artifacts = RunArtifacts(run_id=run_id, root=self.base_dir / run_id)
        while artifacts.root.exists():
            run_id = _new_run_id()
            artifacts = RunArtifacts(run_id=run_id, root=self.base_dir / run_id)

        artifacts.root.mkdir(parents=True)
        artifacts.tasks_dir.mkdir()
        artifacts.evaluator_reports_dir.mkdir()
        artifacts.traces_dir.mkdir()
        return artifacts

    def get_run(self, run_id: str) -> RunArtifacts:
        return RunArtifacts(run_id=run_id, root=self.base_dir / run_id)

    def list_runs(self) -> list[RunArtifacts]:
        if not self.base_dir.exists():
            return []

        return [
            RunArtifacts(run_id=path.name, root=path)
            for path in sorted(self.base_dir.iterdir(), reverse=True)
            if path.is_dir()
        ]

    def write_request(self, artifacts: RunArtifacts, request: str) -> Path:
        artifacts.request_path.write_text(request, encoding="utf-8")
        return artifacts.request_path

    def write_spec(self, artifacts: RunArtifacts, spec: str) -> Path:
        artifacts.spec_path.write_text(spec, encoding="utf-8")
        return artifacts.spec_path

    def write_plan(self, artifacts: RunArtifacts, plan: dict[str, Any]) -> Path:
        artifacts.plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return artifacts.plan_path

    def read_plan(self, artifacts: RunArtifacts) -> dict[str, Any]:
        return json.loads(artifacts.plan_path.read_text(encoding="utf-8"))

    def write_task(self, artifacts: RunArtifacts, task_id: str, content: str) -> Path:
        path = artifacts.tasks_dir / f"{task_id}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def write_evaluator_report(
        self,
        artifacts: RunArtifacts,
        task_id: str,
        report: dict[str, Any],
    ) -> Path:
        path = artifacts.evaluator_reports_dir / f"{task_id}.json"
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def append_event(self, artifacts: RunArtifacts, event: dict[str, Any]) -> Path:
        with artifacts.events_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
        return artifacts.events_path

    def write_final_report(self, artifacts: RunArtifacts, report: str) -> Path:
        artifacts.final_report_path.write_text(report, encoding="utf-8")
        return artifacts.final_report_path

    def write_run_summary(self, artifacts: RunArtifacts, summary: dict[str, Any]) -> Path:
        artifacts.run_summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return artifacts.run_summary_path

    def write_state(self, artifacts: RunArtifacts, state: dict[str, Any]) -> Path:
        """Atomically persist state so an interruption never leaves partial JSON."""
        temporary_path = artifacts.state_path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(artifacts.state_path)
        return artifacts.state_path

    def read_state(self, artifacts: RunArtifacts) -> dict[str, Any]:
        if not artifacts.state_path.is_file():
            raise FileNotFoundError(f"Harness state not found: {artifacts.state_path}")
        state = json.loads(artifacts.state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError(f"Harness state must be a JSON object: {artifacts.state_path}")
        return state


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def build_run_summary(artifacts: RunArtifacts, *, status: str) -> dict[str, Any]:
    """Create the sole structured source for a completed harness run."""
    traces: list[dict[str, Any]] = []
    if artifacts.traces_dir.is_dir():
        for path in sorted(artifacts.traces_dir.glob("*.jsonl")):
            if path.name != artifacts.model_calls_path.name:
                traces.extend(read_jsonl(path))
    model_calls = read_jsonl(artifacts.model_calls_path)
    trace_summary = TraceSummary.from_events(traces)
    stop_reasons: dict[str, int] = {}
    for call in model_calls:
        reason = str(call.get("stop_reason") or "unknown")
        stop_reasons[reason] = stop_reasons.get(reason, 0) + 1
    known_costs = [call["estimated_cost_usd"] for call in model_calls if call.get("estimated_cost_usd") is not None]
    return {
        "schema_version": 1,
        "run_id": artifacts.run_id,
        "status": status,
        "tool": trace_summary.to_dict(),
        "model": {
            "calls": len(model_calls),
            "duration_ms": sum(int(call.get("duration_ms", 0)) for call in model_calls),
            "input_tokens": sum(int(call.get("input_tokens", 0)) for call in model_calls),
            "output_tokens": sum(int(call.get("output_tokens", 0)) for call in model_calls),
            "cache_read_input_tokens": sum(int(call.get("cache_read_input_tokens", 0)) for call in model_calls),
            "stop_reasons": dict(sorted(stop_reasons.items())),
            "estimated_cost_usd": sum(float(cost) for cost in known_costs) if known_costs else None,
        },
    }
