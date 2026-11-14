"""Auditable records for memory context injected into an agent run."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from miniclaudecode.memory.records import ContextBundle
from miniclaudecode.memory.store import MemoryStore


class ContextInjectionRecorder:
    """Append inspectable context-selection events to project memory storage."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def record(self, run_id: str, bundle: ContextBundle, rendered_context: str) -> Path:
        """Record every source included in an injected context bundle."""
        event = {
            "schema_version": 1,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "task": bundle.task,
            "rendered_chars": len(rendered_context),
            "sources": _sources(bundle),
        }
        self.store.ensure_dirs()
        path = self.store.context_injections_path
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return path


def has_injectable_memory(bundle: ContextBundle) -> bool:
    """Return whether a bundle contains persisted memory beyond its task label."""
    return bool(
        bundle.project_summary.strip()
        or bundle.file_summaries
        or bundle.decisions
        or bundle.task_memories
    )


def _sources(bundle: ContextBundle) -> list[dict[str, Any]]:
    task_keywords = _keywords(bundle.task)
    sources: list[dict[str, Any]] = []
    if bundle.project_summary.strip():
        sources.append(
            {
                "kind": "project_summary",
                "source": "memory/project.md",
                "reason": "project summary is always included when available",
            }
        )
    for file_summary in bundle.file_summaries:
        sources.append(
            {
                "kind": "file_summary",
                "source": f"memory/files/{file_summary.path}",
                "reason": _matching_reason(
                    task_keywords,
                    [
                        file_summary.path,
                        file_summary.language,
                        *file_summary.symbols,
                        file_summary.summary,
                    ],
                ),
            }
        )
    for decision in bundle.decisions:
        sources.append(
            {
                "kind": "decision",
                "source": f"memory/decisions/{decision.id}",
                "reason": _matching_reason(
                    task_keywords,
                    [
                        decision.id,
                        decision.title,
                        decision.context,
                        decision.decision,
                        *decision.consequences,
                    ],
                    fallback="selected for engineering relevance",
                ),
            }
        )
    for task_memory in bundle.task_memories:
        sources.append(
            {
                "kind": "task_memory",
                "source": f"memory/tasks/{task_memory.id}",
                "reason": _matching_reason(
                    task_keywords,
                    [
                        task_memory.id,
                        task_memory.goal,
                        *task_memory.changed_files,
                        *task_memory.tests,
                        task_memory.result,
                        task_memory.summary,
                    ],
                    fallback="selected as a recent task-memory fallback",
                ),
            }
        )
    return sources


def _keywords(text: str) -> set[str]:
    return {token.lower() for token in text.replace("/", " ").split() if len(token) >= 2}


def _matching_reason(keywords: set[str], parts: list[str], fallback: str = "selected by task relevance") -> str:
    haystack = " ".join(parts).lower()
    matched = sorted(keyword for keyword in keywords if keyword in haystack)
    if matched:
        return f"matched task keywords: {', '.join(matched)}"
    return fallback
