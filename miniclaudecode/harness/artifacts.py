"""Artifact paths for long-running harness runs."""

from __future__ import annotations

import uuid
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


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
