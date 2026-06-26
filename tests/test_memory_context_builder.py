"""Tests for memory context selection and rendering."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from miniclaudecode.memory import (
    ContextBuilder,
    DecisionRecord,
    FileSummary,
    MemoryStore,
    ProjectSummary,
    TaskMemory,
)


class TestContextBuilder(unittest.TestCase):
    def test_build_includes_project_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            store.write_project_summary(_project_summary())

            bundle = ContextBuilder(store).build("Implement memory context")

            self.assertIn("miniClaudeCode", bundle.project_summary)
            self.assertIn("memory", bundle.project_summary)

    def test_build_selects_relevant_file_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            relevant = _file_summary(
                "miniclaudecode/memory/context_builder.py",
                symbols=["ContextBuilder"],
                summary="Builds memory context for the current task.",
            )
            unrelated = _file_summary(
                "miniclaudecode/tools/bash_tool.py",
                symbols=["BashTool"],
                summary="Executes shell commands.",
            )
            store.write_file_summary(unrelated)
            store.write_file_summary(relevant)

            bundle = ContextBuilder(store).build("Fix ContextBuilder memory selection")

            self.assertEqual([item.path for item in bundle.file_summaries], [relevant.path])

    def test_build_prefers_recent_task_memories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            store.write_task_memory(_task_memory("task-001", "Old runtime work"))
            store.write_task_memory(_task_memory("task-003", "Recent git work"))
            store.write_task_memory(_task_memory("task-002", "Middle memory work"))

            bundle = ContextBuilder(store, max_task_memories=2).build("general follow up")

            self.assertEqual([item.id for item in bundle.task_memories], ["task-003", "task-002"])

    def test_build_scores_matching_task_memories_before_recent_ones(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            store.write_task_memory(
                _task_memory(
                    "task-009",
                    "Recent unrelated git work",
                    changed_files=["miniclaudecode/git_workflow/workflow.py"],
                    tests=["python -m unittest tests.test_git_workflow_workflow"],
                )
            )
            store.write_task_memory(_task_memory("task-001", "Old memory context work"))

            bundle = ContextBuilder(store, max_task_memories=1).build("memory context")

            self.assertEqual([item.id for item in bundle.task_memories], ["task-001"])

    def test_build_selects_engineering_decisions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            selected = DecisionRecord(
                id="decision-001",
                title="Use runtime tracing",
                date="2026-06-20",
                context="Agent runtime needs inspectable tool calls.",
                decision="Persist structured tracing events.",
                consequences=["Easier debugging"],
            )
            unrelated = DecisionRecord(
                id="decision-002",
                title="Use plain text labels",
                date="2026-06-21",
                context="Small formatting choice.",
                decision="Keep labels concise.",
                consequences=["Readable output"],
            )
            store.write_decision(unrelated)
            store.write_decision(selected)

            bundle = ContextBuilder(store).build("runtime observability")

            self.assertEqual([item.id for item in bundle.decisions], [selected.id])

    def test_render_is_stable_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            store.write_project_summary(_project_summary())
            store.write_file_summary(
                _file_summary(
                    "miniclaudecode/memory/context_builder.py",
                    symbols=["ContextBuilder"],
                    summary="Builds compact context.",
                )
            )

            builder = ContextBuilder(store)
            bundle = builder.build("ContextBuilder")

            self.assertEqual(
                builder.render(bundle),
                "\n".join(
                    [
                        "# Project Memory Context",
                        "",
                        "## Current Task",
                        "ContextBuilder",
                        "",
                        "## Project Summary",
                        "Name: miniClaudeCode",
                        "Updated at: 2026-06-24T00:00:00Z",
                        "Modules: runtime, memory",
                        "Capabilities: tool execution, project memory",
                        "Entrypoints: python -m miniclaudecode",
                        "Test commands: python -m unittest discover",
                        "",
                        "## Relevant Files",
                        "### miniclaudecode/memory/context_builder.py",
                        "Language: python",
                        "SHA256: abc123",
                        "Symbols: ContextBuilder",
                        "Builds compact context.",
                        "",
                        "## Engineering Decisions",
                        "None",
                        "",
                        "## Recent Task Memories",
                        "None",
                        "",
                    ]
                ),
            )

    def test_build_limits_rendered_context_chars(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            store.write_project_summary(_project_summary())
            for index in range(10):
                store.write_file_summary(
                    _file_summary(
                        f"miniclaudecode/memory/file_{index}.py",
                        symbols=[f"Symbol{index}"],
                        summary="memory " + ("long summary " * 80),
                    )
                )

            builder = ContextBuilder(store, max_chars=700)
            bundle = builder.build("memory")
            rendered = builder.render(bundle)

            self.assertLessEqual(len(rendered), 700)
            self.assertIn("Project Memory Context", rendered)

    def test_invalid_max_chars_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")

            with self.assertRaises(ValueError):
                ContextBuilder(store, max_chars=0)

            with self.assertRaises(ValueError):
                ContextBuilder(store).build("task", max_chars=0)


def _project_summary() -> ProjectSummary:
    return ProjectSummary(
        name="miniClaudeCode",
        updated_at="2026-06-24T00:00:00Z",
        modules=["runtime", "memory"],
        capabilities=["tool execution", "project memory"],
        entrypoints=["python -m miniclaudecode"],
        test_commands=["python -m unittest discover"],
    )


def _file_summary(path: str, symbols: list[str], summary: str) -> FileSummary:
    return FileSummary(
        path=path,
        sha256="abc123",
        size_bytes=128,
        updated_at="2026-06-24T00:00:00Z",
        language="python",
        symbols=symbols,
        summary=summary,
    )


def _task_memory(
    record_id: str,
    goal: str,
    changed_files: list[str] | None = None,
    tests: list[str] | None = None,
) -> TaskMemory:
    return TaskMemory(
        id=record_id,
        goal=goal,
        changed_files=changed_files or ["miniclaudecode/memory/context_builder.py"],
        tests=tests or ["python -m unittest tests.test_memory_context_builder"],
        result="passed",
        summary=goal,
    )


if __name__ == "__main__":
    unittest.main()
