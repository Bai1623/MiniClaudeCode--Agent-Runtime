"""Tests for memory record data structures."""

from __future__ import annotations

import unittest

from miniclaudecode.memory.records import (
    ContextBundle,
    DecisionRecord,
    FileSummary,
    ProjectSummary,
    TaskMemory,
)


class TestMemoryRecords(unittest.TestCase):
    def test_file_summary_round_trip(self):
        record = FileSummary(
            path="miniclaudecode/agent_loop.py",
            sha256="abc123",
            size_bytes=42,
            updated_at="2026-06-22T00:00:00Z",
            language="python",
            symbols=["AgentLoop", "run"],
            summary="Agent loop orchestration.",
        )

        self.assertEqual(FileSummary.from_dict(record.to_dict()), record)

    def test_project_summary_round_trip(self):
        record = ProjectSummary(
            name="miniClaudeCode",
            updated_at="2026-06-22T00:00:00Z",
            modules=["runtime", "harness"],
            capabilities=["tool execution", "task harness"],
            entrypoints=["python -m miniclaudecode"],
            test_commands=["python -m unittest discover"],
        )

        self.assertEqual(ProjectSummary.from_dict(record.to_dict()), record)

    def test_decision_record_round_trip(self):
        record = DecisionRecord(
            id="2026-06-22-memory",
            title="Use file based memory",
            date="2026-06-22",
            context="The project needs inspectable memory.",
            decision="Store memory as local markdown and structured records.",
            consequences=["No database dependency", "Easy to review"],
        )

        self.assertEqual(DecisionRecord.from_dict(record.to_dict()), record)

    def test_task_memory_round_trip(self):
        record = TaskMemory(
            id="run-001",
            goal="Add memory records",
            changed_files=["miniclaudecode/memory/records.py"],
            tests=["python -m unittest tests.test_memory_records"],
            result="passed",
            summary="Added memory record dataclasses.",
        )

        self.assertEqual(TaskMemory.from_dict(record.to_dict()), record)

    def test_context_bundle_round_trip(self):
        file_summary = FileSummary(
            path="miniclaudecode/memory/records.py",
            sha256="abc123",
            size_bytes=100,
            updated_at="2026-06-22T00:00:00Z",
            language="python",
            symbols=["FileSummary"],
            summary="Memory record definitions.",
        )
        decision = DecisionRecord(
            id="decision-001",
            title="Use deterministic memory",
            date="2026-06-22",
            context="Keep first version testable.",
            decision="Avoid vector database.",
            consequences=["Lower setup cost"],
        )
        task_memory = TaskMemory(
            id="task-001",
            goal="Build memory records",
            changed_files=["records.py"],
            tests=["unit tests"],
            result="passed",
            summary="Records complete.",
        )
        bundle = ContextBundle(
            task="Implement memory store",
            project_summary="miniClaudeCode memory layer",
            file_summaries=[file_summary],
            decisions=[decision],
            task_memories=[task_memory],
        )

        self.assertEqual(ContextBundle.from_dict(bundle.to_dict()), bundle)

    def test_list_fields_reject_non_lists(self):
        data = {
            "path": "file.py",
            "sha256": "abc",
            "size_bytes": 1,
            "updated_at": "now",
            "language": "python",
            "symbols": "not-a-list",
            "summary": "summary",
        }

        with self.assertRaises(TypeError):
            FileSummary.from_dict(data)


if __name__ == "__main__":
    unittest.main()
