"""Central tool execution runtime."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, TextIO, Union

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


ConfirmCallback = Callable[[str, ToolResult], Union[bool, str]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_confirm_callback(tool_name: str, preview: ToolResult) -> str:
    prompt = _format_preview_prompt(tool_name, preview)
    try:
        answer = input(prompt).strip().lower()
        return _parse_permission_answer(answer)
    except (EOFError, KeyboardInterrupt):
        return "deny"


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
        self._permanent_preview_allows: set[tuple[str, str]] = set()

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

        target = _target_from_params(tool.name, params)
        allow_key = (tool.name, target)
        preview = _with_preview_metadata(tool.name, target, preview)
        self.output.write(_format_preview_summary(tool.name, preview))
        self.output.write("\n[Diff]\n")
        self.output.write(preview.output)
        if not preview.output.endswith("\n"):
            self.output.write("\n")
        self.output.flush()

        if self.config.permission_mode == PermissionMode.ASK:
            if allow_key in self._permanent_preview_allows:
                return None
            decision = _normalize_permission_decision(self.confirm_callback(tool.name, preview))
            if decision == "always":
                self._permanent_preview_allows.add(allow_key)
                return None
            if decision != "once":
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


def _target_from_params(tool_name: str, params: dict) -> str:
    if tool_name in {"write_file", "edit_file"}:
        return str(params.get("path", "(unknown)"))
    if tool_name == "bash":
        return str(params.get("command", "(unknown)"))
    return repr(sorted(params.items()))


def _with_preview_metadata(tool_name: str, target: str, preview: ToolResult) -> ToolResult:
    metadata = dict(preview.metadata)
    metadata["tool_name"] = tool_name
    metadata["target"] = target
    metadata["diff_summary"] = _summarize_diff(preview.output)
    return ToolResult(
        output=preview.output,
        is_error=preview.is_error,
        error_type=preview.error_type,
        metadata=metadata,
    )


def _format_preview_summary(tool_name: str, preview: ToolResult) -> str:
    target = preview.metadata.get("target", "(unknown)")
    diff_summary = preview.metadata.get("diff_summary", "diff summary unavailable")
    return (
        "\n[Permission Request]\n"
        f"Tool: {tool_name}\n"
        f"Target: {target}\n"
        "Why: this tool will modify workspace files.\n"
        f"Diff summary: {diff_summary}\n"
    )


def _format_preview_prompt(tool_name: str, preview: ToolResult) -> str:
    target = preview.metadata.get("target", "(unknown)")
    diff_summary = preview.metadata.get("diff_summary", "diff summary unavailable")
    return (
        "\n[Permission Decision]\n"
        f"Tool: {tool_name}\n"
        f"Target: {target}\n"
        f"Diff summary: {diff_summary}\n"
        "Choose: [o]nce / [a]lways / [d]eny > "
    )


def _summarize_diff(diff: str) -> str:
    additions = 0
    deletions = 0
    files: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            files.append(line[6:])
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    file_text = ", ".join(files) if files else "unknown file"
    return f"{file_text}; +{additions} -{deletions}"


def _parse_permission_answer(answer: str) -> str:
    if answer in {"o", "once", "y", "yes"}:
        return "once"
    if answer in {"a", "always", "permanent", "p"}:
        return "always"
    return "deny"


def _normalize_permission_decision(decision: bool | str) -> str:
    if isinstance(decision, bool):
        return "once" if decision else "deny"
    return _parse_permission_answer(decision.strip().lower())
