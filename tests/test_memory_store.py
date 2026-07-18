"""Tests for file-backed project memory storage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from miniclaudecode.memory import (
    DecisionRecord,
    FileSummary,
    MemoryStore,
    ProjectSummary,
    TaskMemory,
)


class TestMemoryStore(unittest.TestCase):
    def test_ensure_dirs_creates_memory_layout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "memory"
            store = MemoryStore(base_dir)

            self.assertEqual(store.ensure_dirs(), base_dir)
            self.assertTrue(base_dir.is_dir())
            self.assertTrue(store.files_dir.is_dir())
            self.assertTrue(store.decisions_dir.is_dir())
            self.assertTrue(store.tasks_dir.is_dir())
            self.assertTrue(store.context_dir.is_dir())

    def test_project_summary_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            summary = _project_summary()

            path = store.write_project_summary(summary)

            self.assertEqual(path, store.project_path)
            self.assertEqual(store.read_project_summary(), summary)
            self.assertIn("# Project Memory: miniClaudeCode", path.read_text("utf-8"))

    def test_missing_project_summary_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")

            self.assertIsNone(store.read_project_summary())

    def test_file_summary_round_trip_uses_safe_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            summary = _file_summary("miniclaudecode/memory/store.py")

            path = store.write_file_summary(summary)

            self.assertEqual(store.read_file_summary(summary.path), summary)
            self.assertEqual(path.parent, store.files_dir)
            self.assertNotIn("/", path.name)
            self.assertIn("# File Memory:", path.read_text("utf-8"))

    def test_file_summary_names_do_not_collide(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            first = _file_summary("src/a:b.py")
            second = _file_summary("src/a?b.py")

            first_path = store.write_file_summary(first)
            second_path = store.write_file_summary(second)

            self.assertNotEqual(first_path, second_path)
            self.assertEqual(store.read_file_summary(first.path), first)
            self.assertEqual(store.read_file_summary(second.path), second)

    def test_record_content_preserves_unicode_and_comment_tokens(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            summary = FileSummary(
                path="文档/设计.md",
                sha256="abc123",
                size_bytes=32,
                updated_at="2026-06-24T00:00:00Z",
                language="markdown",
                symbols=["长期记忆"],
                summary="保留中文和 --> 注释结束符。",
            )

            store.write_file_summary(summary)

            self.assertEqual(store.read_file_summary(summary.path), summary)

    def test_list_file_summaries_is_sorted_by_source_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            store.write_file_summary(_file_summary("z.py"))
            store.write_file_summary(_file_summary("a.py"))

            summaries = store.list_file_summaries()

            self.assertEqual([item.path for item in summaries], ["a.py", "z.py"])

    def test_decisions_round_trip_and_sort_by_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            later = _decision("decision-002")
            earlier = _decision("decision-001")

            store.write_decision(later)
            store.write_decision(earlier)

            self.assertEqual(store.list_decisions(), [earlier, later])

    def test_task_memories_round_trip_and_sort_by_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            later = _task_memory("task-002")
            earlier = _task_memory("task-001")

            store.write_task_memory(later)
            store.write_task_memory(earlier)

            self.assertEqual(store.list_task_memories(), [earlier, later])

    def test_write_context_creates_markdown_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")

            path = store.write_context("latest", "# Context\n")

            self.assertEqual(path, store.context_dir / "latest.md")
            self.assertEqual(path.read_text(encoding="utf-8"), "# Context\n")

    def test_list_methods_return_empty_without_creating_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "memory"
            store = MemoryStore(base_dir)

            self.assertEqual(store.list_file_summaries(), [])
            self.assertEqual(store.list_decisions(), [])
            self.assertEqual(store.list_task_memories(), [])
            self.assertFalse(base_dir.exists())

    def test_invalid_record_reports_its_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            store.ensure_dirs()
            invalid_path = store.files_dir / "invalid.md"
            invalid_path.write_text("not a memory record", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, str(invalid_path).replace("\\", "\\\\")):
                store.list_file_summaries()


def _project_summary() -> ProjectSummary:
    return ProjectSummary(
        name="miniClaudeCode",
        updated_at="2026-06-24T00:00:00Z",
        modules=["runtime", "memory"],
        capabilities=["tool execution", "project memory"],
        entrypoints=["python -m miniclaudecode"],
        test_commands=["python -m unittest discover"],
    )


def _file_summary(path: str) -> FileSummary:
    return FileSummary(
        path=path,
        sha256="abc123",
        size_bytes=128,
        updated_at="2026-06-24T00:00:00Z",
        language="python",
        symbols=["MemoryStore"],
        summary="Stores project memory records.",
    )


def _decision(record_id: str) -> DecisionRecord:
    return DecisionRecord(
        id=record_id,
        title="Use file-backed memory",
        date="2026-06-24",
        context="Memory must remain inspectable.",
        decision="Persist records as Markdown with structured metadata.",
        consequences=["No database dependency"],
    )


def _task_memory(record_id: str) -> TaskMemory:
    return TaskMemory(
        id=record_id,
        goal="Implement MemoryStore",
        changed_files=["miniclaudecode/memory/store.py"],
        tests=["python -m unittest tests.test_memory_store"],
        result="passed",
        summary="Added file-backed memory storage.",
    )


if __name__ == "__main__":
    unittest.main()
