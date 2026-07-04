"""Structured records for project memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol, TypeVar


@dataclass(frozen=True)
class FileSummary:
    path: str
    sha256: str
    size_bytes: int
    updated_at: str
    language: str
    symbols: list[str]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileSummary:
        return cls(
            path=str(data["path"]),
            sha256=str(data["sha256"]),
            size_bytes=int(data["size_bytes"]),
            updated_at=str(data["updated_at"]),
            language=str(data["language"]),
            symbols=_string_list(data.get("symbols", [])),
            summary=str(data["summary"]),
        )


@dataclass(frozen=True)
class ProjectSummary:
    name: str
    updated_at: str
    modules: list[str]
    capabilities: list[str]
    entrypoints: list[str]
    test_commands: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectSummary:
        return cls(
            name=str(data["name"]),
            updated_at=str(data["updated_at"]),
            modules=_string_list(data.get("modules", [])),
            capabilities=_string_list(data.get("capabilities", [])),
            entrypoints=_string_list(data.get("entrypoints", [])),
            test_commands=_string_list(data.get("test_commands", [])),
        )


@dataclass(frozen=True)
class DecisionRecord:
    id: str
    title: str
    date: str
    context: str
    decision: str
    consequences: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionRecord:
        return cls(
            id=str(data["id"]),
            title=str(data["title"]),
            date=str(data["date"]),
            context=str(data["context"]),
            decision=str(data["decision"]),
            consequences=_string_list(data.get("consequences", [])),
        )


@dataclass(frozen=True)
class TaskMemory:
    id: str
    goal: str
    changed_files: list[str]
    tests: list[str]
    result: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskMemory:
        return cls(
            id=str(data["id"]),
            goal=str(data["goal"]),
            changed_files=_string_list(data.get("changed_files", [])),
            tests=_string_list(data.get("tests", [])),
            result=str(data["result"]),
            summary=str(data["summary"]),
        )


@dataclass(frozen=True)
class ContextBundle:
    task: str
    project_summary: str
    file_summaries: list[FileSummary]
    decisions: list[DecisionRecord]
    task_memories: list[TaskMemory]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "project_summary": self.project_summary,
            "file_summaries": [item.to_dict() for item in self.file_summaries],
            "decisions": [item.to_dict() for item in self.decisions],
            "task_memories": [item.to_dict() for item in self.task_memories],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextBundle:
        return cls(
            task=str(data["task"]),
            project_summary=str(data["project_summary"]),
            file_summaries=_record_list(FileSummary, data.get("file_summaries", [])),
            decisions=_record_list(DecisionRecord, data.get("decisions", [])),
            task_memories=_record_list(TaskMemory, data.get("task_memories", [])),
        )


class RecordLoader(Protocol):
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Any: ...


RecordT = TypeVar("RecordT", bound=RecordLoader)


def _record_list(record_type: type[RecordT], items: Any) -> list[RecordT]:
    if not isinstance(items, list):
        raise TypeError("Expected a list of record dictionaries.")
    return [record_type.from_dict(item) for item in items]


def _string_list(items: Any) -> list[str]:
    if not isinstance(items, list):
        raise TypeError("Expected a list.")
    return [str(item) for item in items]
