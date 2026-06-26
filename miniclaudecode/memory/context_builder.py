"""Build compact task context from persisted project memory."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Iterable

from miniclaudecode.memory.records import (
    ContextBundle,
    DecisionRecord,
    FileSummary,
    ProjectSummary,
    TaskMemory,
)
from miniclaudecode.memory.store import MemoryStore


DEFAULT_MAX_CONTEXT_CHARS = 12_000
ENGINEERING_KEYWORDS = {
    "agent",
    "architecture",
    "context",
    "git",
    "harness",
    "memory",
    "runtime",
    "tool",
    "workflow",
}


class ContextBuilder:
    """Selects and renders the most useful memory records for a task."""

    def __init__(
        self,
        store: MemoryStore,
        max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
        max_file_summaries: int = 12,
        max_decisions: int = 5,
        max_task_memories: int = 5,
    ) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars must be positive.")

        self.store = store
        self.max_chars = max_chars
        self.max_file_summaries = max_file_summaries
        self.max_decisions = max_decisions
        self.max_task_memories = max_task_memories

    def build(self, task: str, max_chars: int | None = None) -> ContextBundle:
        budget = max_chars if max_chars is not None else self.max_chars
        if budget <= 0:
            raise ValueError("max_chars must be positive.")

        keywords = _keywords(task)
        project_summary = _render_project_summary(self.store.read_project_summary())
        file_summaries = self._select_file_summaries(keywords)
        decisions = self._select_decisions(keywords)
        task_memories = self._select_task_memories(keywords)

        bundle = ContextBundle(
            task=task,
            project_summary=project_summary,
            file_summaries=file_summaries,
            decisions=decisions,
            task_memories=task_memories,
        )
        return self._fit_budget(bundle, budget)

    def render(self, bundle: ContextBundle) -> str:
        sections = [
            "# Project Memory Context",
            "",
            "## Current Task",
            _clean_text(bundle.task) or "None",
            "",
            "## Project Summary",
            bundle.project_summary.strip() or "None",
            "",
            "## Relevant Files",
            _render_file_summaries(bundle.file_summaries),
            "",
            "## Engineering Decisions",
            _render_decisions(bundle.decisions),
            "",
            "## Recent Task Memories",
            _render_task_memories(bundle.task_memories),
        ]
        return "\n".join(sections).rstrip() + "\n"

    def _select_file_summaries(self, keywords: set[str]) -> list[FileSummary]:
        scored = [
            (_score_text(keywords, item.path, item.language, " ".join(item.symbols), item.summary), item)
            for item in self.store.list_file_summaries()
        ]
        return [
            item
            for score, item in sorted(scored, key=lambda pair: (-pair[0], pair[1].path))
            if score > 0
        ][: self.max_file_summaries]

    def _select_decisions(self, keywords: set[str]) -> list[DecisionRecord]:
        scored = []
        for item in self.store.list_decisions():
            text_score = _score_text(
                keywords,
                item.id,
                item.title,
                item.context,
                item.decision,
                " ".join(item.consequences),
            )
            engineering_score = _score_text(
                ENGINEERING_KEYWORDS,
                item.id,
                item.title,
                item.context,
                item.decision,
            )
            score = text_score + min(engineering_score, 3)
            scored.append((score, item))

        return [
            item
            for score, item in sorted(scored, key=lambda pair: (-pair[0], pair[1].date, pair[1].id))
            if score > 0
        ][: self.max_decisions]

    def _select_task_memories(self, keywords: set[str]) -> list[TaskMemory]:
        scored = [
            (
                _score_text(
                    keywords,
                    item.id,
                    item.goal,
                    " ".join(item.changed_files),
                    " ".join(item.tests),
                    item.result,
                    item.summary,
                ),
                item,
            )
            for item in self.store.list_task_memories()
        ]
        return [
            item
            for _, item in sorted(scored, key=lambda pair: (pair[0], pair[1].id), reverse=True)
        ][: self.max_task_memories]

    def _fit_budget(self, bundle: ContextBundle, max_chars: int) -> ContextBundle:
        current = bundle
        while len(self.render(current)) > max_chars:
            if current.task_memories:
                current = replace(current, task_memories=current.task_memories[:-1])
                continue
            if current.decisions:
                current = replace(current, decisions=current.decisions[:-1])
                continue
            if current.file_summaries:
                current = replace(current, file_summaries=current.file_summaries[:-1])
                continue

            current = replace(
                current,
                project_summary=_truncate_text(current.project_summary, max_chars // 2),
            )
            break

        rendered = self.render(current)
        if len(rendered) <= max_chars:
            return current

        return replace(
            current,
            project_summary=_truncate_text(
                current.project_summary,
                max(0, len(current.project_summary) - (len(rendered) - max_chars)),
            ),
        )


def _render_project_summary(summary: ProjectSummary | None) -> str:
    if summary is None:
        return ""

    return "\n".join(
        [
            f"Name: {summary.name}",
            f"Updated at: {summary.updated_at}",
            f"Modules: {_join_or_none(summary.modules)}",
            f"Capabilities: {_join_or_none(summary.capabilities)}",
            f"Entrypoints: {_join_or_none(summary.entrypoints)}",
            f"Test commands: {_join_or_none(summary.test_commands)}",
        ]
    )


def _render_file_summaries(items: list[FileSummary]) -> str:
    if not items:
        return "None"

    rendered = []
    for item in items:
        symbols = _join_or_none(item.symbols)
        rendered.append(
            "\n".join(
                [
                    f"### {item.path}",
                    f"Language: {item.language}",
                    f"SHA256: {item.sha256}",
                    f"Symbols: {symbols}",
                    _clean_text(item.summary),
                ]
            )
        )
    return "\n\n".join(rendered)


def _render_decisions(items: list[DecisionRecord]) -> str:
    if not items:
        return "None"

    rendered = []
    for item in items:
        rendered.append(
            "\n".join(
                [
                    f"### {item.title}",
                    f"ID: {item.id}",
                    f"Date: {item.date}",
                    f"Context: {_clean_text(item.context)}",
                    f"Decision: {_clean_text(item.decision)}",
                    f"Consequences: {_join_or_none(item.consequences)}",
                ]
            )
        )
    return "\n\n".join(rendered)


def _render_task_memories(items: list[TaskMemory]) -> str:
    if not items:
        return "None"

    rendered = []
    for item in items:
        rendered.append(
            "\n".join(
                [
                    f"### {item.id}",
                    f"Goal: {_clean_text(item.goal)}",
                    f"Changed files: {_join_or_none(item.changed_files)}",
                    f"Tests: {_join_or_none(item.tests)}",
                    f"Result: {_clean_text(item.result)}",
                    f"Summary: {_clean_text(item.summary)}",
                ]
            )
        )
    return "\n\n".join(rendered)


def _keywords(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_./-]+", text)
        if len(token) >= 2
    }


def _score_text(keywords: set[str], *parts: str) -> int:
    if not keywords:
        return 0

    haystack = " ".join(parts).lower()
    score = 0
    for keyword in keywords:
        if keyword in haystack:
            score += 1
    return score


def _join_or_none(items: Iterable[str]) -> str:
    values = [str(item) for item in items if str(item)]
    return ", ".join(values) if values else "None"


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= len("... [truncated]"):
        return text[:max_chars]
    return text[: max_chars - len("... [truncated]")].rstrip() + "... [truncated]"
