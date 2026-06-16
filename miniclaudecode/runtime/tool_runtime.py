"""Central tool execution runtime."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, TextIO

from miniclaudecode.config import Config, PermissionMode
from miniclaudecode.permissions import PermissionGate
from miniclaudecode.runtime.compression import compress_tool_result
from miniclaudecode.runtime.schema_validator import validate_tool_input
from miniclaudecode.runtime.tracing import TraceRecorder
from miniclaudecode.tools.base import Tool, ToolRegistry, ToolResult

RETRYABLE_ERROR_TYPES = {"timeout_error", "execution_error"}


@dataclass(frozen=True)
class ToolExecution:
    tool_use_id: str
    result: ToolResult

    def to_api_result(self) -> dict:
        return {
            "type": "tool_result",
            "tool_use_id": self.tool_use_id,
            "content": self.result.output,
            "is_error": self.result.is_error,
        }


ConfirmCallback = Callable[[str, ToolResult], bool]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_confirm_callback(tool_name: str, preview: ToolResult) -> bool:
    prompt = f"\n[Permission] Apply diff for '{tool_name}'? [y/N] "
    try:
        answer = input(prompt).strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


class ToolRuntime:
    """Coordinates validation, permission checks, execution, and tracing."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        permission_gate: PermissionGate,
        config: Config,
        tracer: TraceRecorder | None = None,
        confirm_callback: ConfirmCallback | None = None,
        output: TextIO | None = None,
    ) -> None:
        self.registry = registry
        self.permission_gate = permission_gate
        self.config = config
        self.tracer = tracer or TraceRecorder(enabled=False)
        self.confirm_callback = confirm_callback or _default_confirm_callback
        self.output = output or sys.stdout

    def invoke(self, call: dict, turn: int, run_id: str) -> ToolExecution:
        started_at = _utc_now()
        tool_name = call.get("name", "")
        params = self._call_input(call)

        tool = self.registry.get(tool_name)
        if tool is None:
            result = ToolResult(
                output=f"Error: unknown tool '{tool_name}'",
                is_error=True,
                error_type="unknown_tool",
            )
            return self._finish(call, tool_name, params, result, started_at, turn, run_id)

        validation = validate_tool_input(tool, params)
        if validation is not None:
            return self._finish(call, tool.name, params, validation, started_at, turn, run_id)

        denial = self.permission_gate.check(tool, params)
        if denial is not None:
            result = ToolResult(
                output=denial.output,
                is_error=True,
                error_type="permission_denied",
                metadata=denial.metadata,
            )
            return self._finish(call, tool.name, params, result, started_at, turn, run_id)

        preview_result = self._handle_preview(tool, params)
        if preview_result is not None:
            return self._finish(call, tool.name, params, preview_result, started_at, turn, run_id)

        result = self._execute_with_retry(tool, params)
        return self._finish(call, tool.name, params, result, started_at, turn, run_id)

    @staticmethod
    def _call_input(call: dict) -> dict:
        params = call.get("input", {})
        if isinstance(params, dict):
            return params
        return {"_raw_input": params}

    def _handle_preview(self, tool: Tool, params: dict) -> ToolResult | None:
        preview = tool.preview(params)
        if preview is None:
            return None
        if preview.is_error:
            return self._ensure_error_type(preview, "execution_error")

        self.output.write("\n[Diff Preview]\n")
        self.output.write(preview.output)
        if not preview.output.endswith("\n"):
            self.output.write("\n")
        self.output.flush()

        if self.config.permission_mode == PermissionMode.ASK:
            if not self.confirm_callback(tool.name, preview):
                return ToolResult(
                    output="Permission denied: user rejected diff preview.",
                    is_error=True,
                    error_type="preview_rejected",
                )
        return None

    def _execute_once(self, tool: Tool, params: dict) -> ToolResult:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(tool.execute, params)
        try:
            return future.result(timeout=tool.timeout_seconds)
        except TimeoutError:
            future.cancel()
            return ToolResult(
                output=f"Error: tool '{tool.name}' timed out after {tool.timeout_seconds}s",
                is_error=True,
                error_type="timeout_error",
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _execute_with_retry(self, tool: Tool, params: dict) -> ToolResult:
        result = self._ensure_error_type(self._execute_once(tool, params), "execution_error")
        if not result.is_error:
            return result
        if not tool.retryable:
            return result
        if result.error_type not in RETRYABLE_ERROR_TYPES:
            return result

        retry = self._ensure_error_type(self._execute_once(tool, params), "execution_error")
        metadata = dict(retry.metadata)
        metadata["retried"] = True
        return ToolResult(
            output=retry.output,
            is_error=retry.is_error,
            error_type=retry.error_type,
            metadata=metadata,
        )

    @staticmethod
    def _ensure_error_type(result: ToolResult, fallback: str) -> ToolResult:
        if not result.is_error or result.error_type is not None:
            return result
        return ToolResult(
            output=result.output,
            is_error=True,
            error_type=fallback,
            metadata=result.metadata,
        )

    def _finish(
        self,
        call: dict,
        tool_name: str,
        params: dict,
        result: ToolResult,
        started_at: datetime,
        turn: int,
        run_id: str,
    ) -> ToolExecution:
        compressed = compress_tool_result(
            result,
            max_chars=self.config.max_tool_result_chars,
            head_chars=self.config.tool_result_head_chars,
            tail_chars=self.config.tool_result_tail_chars,
        )
        ended_at = _utc_now()
        tool_call_id = call.get("id", "")
        self.tracer.record_tool_call(
            run_id=run_id,
            turn=turn,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            params=params,
            result=compressed,
            started_at=started_at,
            ended_at=ended_at,
        )
        return ToolExecution(tool_use_id=tool_call_id, result=compressed)
