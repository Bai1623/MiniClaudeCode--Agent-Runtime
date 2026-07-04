"""File-backed storage for project memory records."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, TypeVar

from miniclaudecode.memory.records import (
    DecisionRecord,
    FileSummary,
    ProjectSummary,
    TaskMemory,
)

RecordT = TypeVar("RecordT")
_METADATA_START = "<!-- miniclaudecode-memory:v1"
_METADATA_END = "miniclaudecode-memory:end -->"


class MemoryStore:
    """Persists inspectable memory records below a local directory."""

    def __init__(
        self,
        base_dir: str | Path = ".miniclaudecode/memory",
    ) -> None:
        self.base_dir = Path(base_dir)

    @property
    def project_path(self) -> Path:
        return self.base_dir / "project.md"

    @property
    def files_dir(self) -> Path:
        return self.base_dir / "files"

    @property
    def decisions_dir(self) -> Path:
        return self.base_dir / "decisions"

    @property
    def tasks_dir(self) -> Path:
        return self.base_dir / "tasks"

    @property
    def context_dir(self) -> Path:
        return self.base_dir / "context"

    def ensure_dirs(self) -> Path:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        for directory in (
            self.files_dir,
            self.decisions_dir,
            self.tasks_dir,
            self.context_dir,
        ):
            directory.mkdir(exist_ok=True)
        return self.base_dir

    def write_project_summary(self, summary: ProjectSummary) -> Path:
        self.ensure_dirs()
        return self._write_record(
            self.project_path,
            summary.to_dict(),
            _render_project_summary(summary),
        )

    def read_project_summary(self) -> ProjectSummary | None:
        return self._read_record(self.project_path, ProjectSummary.from_dict)

    def write_file_summary(self, summary: FileSummary) -> Path:
        self.ensure_dirs()
        path = self.files_dir / f"{_safe_name(summary.path)}.md"
        return self._write_record(
            path,
            summary.to_dict(),
            _render_file_summary(summary),
        )

    def read_file_summary(self, file_path: str) -> FileSummary | None:
        path = self.files_dir / f"{_safe_name(file_path)}.md"
        return self._read_record(path, FileSummary.from_dict)

    def list_file_summaries(self) -> list[FileSummary]:
        return sorted(
            self._read_directory(self.files_dir, FileSummary.from_dict),
            key=lambda item: item.path,
        )

    def write_decision(self, record: DecisionRecord) -> Path:
        self.ensure_dirs()
        path = self.decisions_dir / f"{_safe_name(record.id)}.md"
        return self._write_record(
            path,
            record.to_dict(),
            _render_decision(record),
        )

    def list_decisions(self) -> list[DecisionRecord]:
        return sorted(
            self._read_directory(self.decisions_dir, DecisionRecord.from_dict),
            key=lambda item: item.id,
        )

    def write_task_memory(self, memory: TaskMemory) -> Path:
        self.ensure_dirs()
        path = self.tasks_dir / f"{_safe_name(memory.id)}.md"
        return self._write_record(
            path,
            memory.to_dict(),
            _render_task_memory(memory),
        )

    def list_task_memories(self) -> list[TaskMemory]:
        return sorted(
            self._read_directory(self.tasks_dir, TaskMemory.from_dict),
            key=lambda item: item.id,
        )

    def _write_record(
        self,
        path: Path,
        data: dict[str, Any],
        markdown: str,
    ) -> Path:
        metadata = json.dumps(data, ensure_ascii=False, indent=2)
        content = (
            f"{_METADATA_START}\n"
            f"{metadata}\n"
            f"{_METADATA_END}\n\n"
            f"{markdown.rstrip()}\n"
        )
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        temporary_path.write_text(content, encoding="utf-8")
        temporary_path.replace(path)
        return path

    def _read_record(
        self,
        path: Path,
        loader: Callable[[dict[str, Any]], RecordT],
    ) -> RecordT | None:
        if not path.is_file():
            return None

        try:
            data = _extract_metadata(path.read_text(encoding="utf-8"))
            return loader(data)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid memory record: {path}") from exc

    def _read_directory(
        self,
        directory: Path,
        loader: Callable[[dict[str, Any]], RecordT],
    ) -> list[RecordT]:
        if not directory.is_dir():
            return []

        records: list[RecordT] = []
        for path in sorted(directory.glob("*.md")):
            record = self._read_record(path, loader)
            if record is not None:
                records.append(record)
        return records


def _safe_name(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", normalized).strip("._")
    slug = slug[:80] or "memory"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{slug}-{digest}"


def _extract_metadata(content: str) -> dict[str, Any]:
    if not content.startswith(_METADATA_START):
        raise ValueError("Memory metadata header is missing.")

    metadata_start = len(_METADATA_START)
    metadata_end = content.find(_METADATA_END, metadata_start)
    if metadata_end < 0:
        raise ValueError("Memory metadata footer is missing.")

    data = json.loads(content[metadata_start:metadata_end].strip())
    if not isinstance(data, dict):
        raise TypeError("Memory metadata must be a JSON object.")
    return data


def _render_project_summary(summary: ProjectSummary) -> str:
    return "\n".join(
        [
            f"# Project Memory: {summary.name}",
            "",
            f"Updated at: {summary.updated_at}",
            "",
            "## Modules",
            _render_lines(summary.modules),
            "",
            "## Capabilities",
            _render_lines(summary.capabilities),
            "",
            "## Entrypoints",
            _render_lines(summary.entrypoints),
            "",
            "## Test Commands",
            _render_lines(summary.test_commands),
        ]
    )


def _render_file_summary(summary: FileSummary) -> str:
    return "\n".join(
        [
            f"# File Memory: {summary.path}",
            "",
            f"SHA256: {summary.sha256}",
            f"Size: {summary.size_bytes} bytes",
            f"Updated at: {summary.updated_at}",
            f"Language: {summary.language}",
            "",
            "## Symbols",
            _render_lines(summary.symbols),
            "",
            "## Summary",
            summary.summary,
        ]
    )


def _render_decision(record: DecisionRecord) -> str:
    return "\n".join(
        [
            f"# Decision: {record.title}",
            "",
            f"ID: {record.id}",
            f"Date: {record.date}",
            "",
            "## Context",
            record.context,
            "",
            "## Decision",
            record.decision,
            "",
            "## Consequences",
            _render_lines(record.consequences),
        ]
    )


def _render_task_memory(memory: TaskMemory) -> str:
    return "\n".join(
        [
            f"# Task Memory: {memory.id}",
            "",
            "## Goal",
            memory.goal,
            "",
            "## Changed Files",
            _render_lines(memory.changed_files),
            "",
            "## Tests",
            _render_lines(memory.tests),
            "",
            f"Result: {memory.result}",
            "",
            "## Summary",
            memory.summary,
        ]
    )


def _render_lines(items: list[str]) -> str:
    if not items:
        return "None"
    return "\n".join(f"- {item}" for item in items)
