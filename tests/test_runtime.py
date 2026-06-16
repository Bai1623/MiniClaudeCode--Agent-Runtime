"""Tests for runtime validation, compression, and tracing helpers."""

from __future__ import annotations

import json
import time
import tempfile
import unittest
from io import StringIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from miniclaudecode.config import Config, PermissionMode
from miniclaudecode.permissions import PermissionGate
from miniclaudecode.runtime.compression import compress_tool_result
from miniclaudecode.runtime.schema_validator import validate_tool_input
from miniclaudecode.runtime.tracing import TraceRecorder, build_input_preview
from miniclaudecode.runtime.tool_runtime import ToolExecution, ToolRuntime
from miniclaudecode.tools.base import Tool, ToolRegistry, ToolResult
from miniclaudecode.tools.file_read import FileReadTool
from miniclaudecode.tools.file_write import FileWriteTool


class SlowTool(Tool):
    @property
    def name(self) -> str:
        return "slow"

    @property
    def description(self) -> str:
        return "Slow test tool."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    @property
    def timeout_seconds(self) -> int:
        return 0.01

    def execute(self, params: dict[str, Any]) -> ToolResult:
        time.sleep(0.05)
        return ToolResult(output="too late")


class FlakyReadTool(Tool):
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "flaky_read"

    @property
    def description(self) -> str:
        return "Fails once, then succeeds."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    @property
    def retryable(self) -> bool:
        return True

    @property
    def is_read_only(self) -> bool:
        return True

    def execute(self, params: dict[str, Any]) -> ToolResult:
        self.calls += 1
        if self.calls == 1:
            return ToolResult(output="temporary failure", is_error=True)
        return ToolResult(output="ok")


class BigOutputTool(Tool):
    @property
    def name(self) -> str:
        return "big_output"

    @property
    def description(self) -> str:
        return "Returns oversized output."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(output="x" * 50)


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


class TestToolExecution(unittest.TestCase):
    def test_to_api_result(self):
        execution = ToolExecution(
            tool_use_id="toolu_test",
            result=ToolResult(output="ok"),
        )
        self.assertEqual(execution.to_api_result(), {
            "type": "tool_result",
            "tool_use_id": "toolu_test",
            "content": "ok",
            "is_error": False,
        })


class TestToolRuntime(unittest.TestCase):
    def make_runtime(
        self,
        registry: ToolRegistry,
        config: Config | None = None,
        tracer: TraceRecorder | None = None,
        confirm_callback=None,
        output=None,
    ) -> ToolRuntime:
        config = config or Config(permission_mode=PermissionMode.AUTO)
        return ToolRuntime(
            registry=registry,
            permission_gate=PermissionGate(config),
            config=config,
            tracer=tracer,
            confirm_callback=confirm_callback,
            output=output or StringIO(),
        )

    def test_unknown_tool_returns_error(self):
        runtime = self.make_runtime(ToolRegistry())
        execution = runtime.invoke({"id": "1", "name": "missing", "input": {}}, turn=1, run_id="run")
        self.assertTrue(execution.result.is_error)
        self.assertEqual(execution.result.error_type, "unknown_tool")

    def test_schema_validation_runs_before_execution(self):
        registry = ToolRegistry()
        registry.register(FileReadTool())
        runtime = self.make_runtime(registry)
        execution = runtime.invoke({"id": "1", "name": "read_file", "input": {}}, turn=1, run_id="run")
        self.assertTrue(execution.result.is_error)
        self.assertEqual(execution.result.error_type, "validation_error")

    def test_permission_denial_is_classified(self):
        registry = ToolRegistry()
        registry.register(FileWriteTool())
        config = Config(permission_mode=PermissionMode.PLAN)
        runtime = self.make_runtime(registry, config=config)
        execution = runtime.invoke(
            {"id": "1", "name": "write_file", "input": {"path": "x.txt", "content": "x"}},
            turn=1,
            run_id="run",
        )
        self.assertTrue(execution.result.is_error)
        self.assertEqual(execution.result.error_type, "permission_denied")

    def test_preview_rejection_prevents_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "preview.txt"
            registry = ToolRegistry()
            registry.register(FileWriteTool())
            config = Config(permission_mode=PermissionMode.ASK)
            runtime = self.make_runtime(
                registry,
                config=config,
                confirm_callback=lambda _tool_name, _preview: False,
            )
            execution = runtime.invoke(
                {"id": "1", "name": "write_file", "input": {"path": str(path), "content": "hello"}},
                turn=1,
                run_id="run",
            )
            self.assertFalse(path.exists())
        self.assertTrue(execution.result.is_error)
        self.assertEqual(execution.result.error_type, "preview_rejected")

    def test_timeout_error(self):
        registry = ToolRegistry()
        registry.register(SlowTool())
        runtime = self.make_runtime(registry)
        execution = runtime.invoke({"id": "1", "name": "slow", "input": {}}, turn=1, run_id="run")
        self.assertTrue(execution.result.is_error)
        self.assertEqual(execution.result.error_type, "timeout_error")

    def test_retryable_tool_retries_execution_error(self):
        tool = FlakyReadTool()
        registry = ToolRegistry()
        registry.register(tool)
        runtime = self.make_runtime(registry)
        execution = runtime.invoke({"id": "1", "name": "flaky_read", "input": {}}, turn=1, run_id="run")
        self.assertFalse(execution.result.is_error)
        self.assertEqual(execution.result.output, "ok")
        self.assertEqual(tool.calls, 2)
        self.assertTrue(execution.result.metadata["retried"])

    def test_result_is_compressed_before_return(self):
        registry = ToolRegistry()
        registry.register(BigOutputTool())
        config = Config(
            permission_mode=PermissionMode.AUTO,
            max_tool_result_chars=10,
            tool_result_head_chars=6,
            tool_result_tail_chars=4,
        )
        runtime = self.make_runtime(registry, config=config)
        execution = runtime.invoke({"id": "1", "name": "big_output", "input": {}}, turn=1, run_id="run")
        self.assertIn("... output truncated ...", execution.result.output)
        self.assertTrue(execution.result.metadata["compressed"])

    def test_trace_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry()
            registry.register(BigOutputTool())
            tracer = TraceRecorder(trace_dir=tmpdir)
            run_id = tracer.start_run()
            runtime = self.make_runtime(registry, tracer=tracer)
            runtime.invoke({"id": "toolu_1", "name": "big_output", "input": {}}, turn=2, run_id=run_id)
            trace_files = list(Path(tmpdir).glob("*.jsonl"))
            self.assertEqual(len(trace_files), 1)
            event = json.loads(trace_files[0].read_text(encoding="utf-8").strip())

        self.assertEqual(event["run_id"], run_id)
        self.assertEqual(event["turn"], 2)
        self.assertEqual(event["tool_call_id"], "toolu_1")
        self.assertEqual(event["tool_name"], "big_output")


if __name__ == "__main__":
    unittest.main()
