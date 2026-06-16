"""Tests for runtime validation, compression, and tracing helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from miniclaudecode.config import Config
from miniclaudecode.runtime.compression import compress_tool_result
from miniclaudecode.runtime.schema_validator import validate_tool_input
from miniclaudecode.runtime.tracing import TraceRecorder, build_input_preview
from miniclaudecode.tools.base import ToolResult
from miniclaudecode.tools.file_read import FileReadTool


class TestSchemaValidator(unittest.TestCase):
    def test_missing_required_field_returns_validation_error(self):
        result = validate_tool_input(FileReadTool(), {})
        self.assertIsNotNone(result)
        self.assertTrue(result.is_error)
        self.assertEqual(result.error_type, "validation_error")
        self.assertIn("path", result.output)

    def test_valid_input_returns_none(self):
        result = validate_tool_input(FileReadTool(), {"path": "README.md"})
        self.assertIsNone(result)


class TestCompression(unittest.TestCase):
    def test_short_output_not_compressed(self):
        result = ToolResult(output="short")
        compressed = compress_tool_result(result, max_chars=10, head_chars=5, tail_chars=5)
        self.assertIs(compressed, result)

    def test_long_output_is_compressed(self):
        result = ToolResult(output="a" * 30, metadata={"source": "test"})
        compressed = compress_tool_result(result, max_chars=10, head_chars=6, tail_chars=4)
        self.assertIn("... output truncated ...", compressed.output)
        self.assertEqual(compressed.metadata["source"], "test")
        self.assertTrue(compressed.metadata["compressed"])
        self.assertEqual(compressed.metadata["original_output_chars"], 30)

    def test_default_config_has_tool_result_limits(self):
        config = Config()
        self.assertEqual(config.max_tool_result_chars, 12_000)
        self.assertEqual(config.tool_result_head_chars, 8_000)
        self.assertEqual(config.tool_result_tail_chars, 4_000)


class TestTracing(unittest.TestCase):
    def test_input_preview_truncates_long_values(self):
        preview = build_input_preview({"content": "x" * 250, "path": "file.txt"})
        self.assertEqual(preview["path"], "file.txt")
        self.assertIn("truncated", preview["content"])
        self.assertLess(len(preview["content"]), 230)

    def test_record_tool_call_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TraceRecorder(trace_dir=tmpdir)
            run_id = recorder.start_run()
            started_at = datetime(2026, 6, 16, 6, 30, 0, tzinfo=timezone.utc)
            ended_at = datetime(2026, 6, 16, 6, 30, 0, 32000, tzinfo=timezone.utc)
            recorder.record_tool_call(
                run_id=run_id,
                turn=1,
                tool_call_id="toolu_test",
                tool_name="grep",
                params={"pattern": "AgentLoop", "path": "."},
                result=ToolResult(output="match", metadata={"compressed": False}),
                started_at=started_at,
                ended_at=ended_at,
            )

            trace_files = list(Path(tmpdir).glob("*.jsonl"))
            self.assertEqual(len(trace_files), 1)
            event = json.loads(trace_files[0].read_text(encoding="utf-8").strip())

        self.assertEqual(event["run_id"], run_id)
        self.assertEqual(event["tool_name"], "grep")
        self.assertEqual(event["status"], "ok")
        self.assertEqual(event["duration_ms"], 32)
        self.assertEqual(event["input_preview"]["pattern"], "AgentLoop")
        self.assertEqual(event["output_chars"], 5)
        self.assertFalse(event["compressed"])


if __name__ == "__main__":
    unittest.main()
