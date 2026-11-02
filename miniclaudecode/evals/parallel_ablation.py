"""Deterministic ablation for sequential versus parallel read-only tool calls."""

from __future__ import annotations

import statistics
import tempfile
import time
from io import StringIO
from pathlib import Path
from typing import Any

from miniclaudecode.agent_loop import AgentLoop
from miniclaudecode.config import Config, PermissionMode
from miniclaudecode.runtime.tracing import TraceRecorder
from miniclaudecode.tools.base import Tool, ToolRegistry, ToolResult


class DelayedReadTool(Tool):
    """A deterministic read-only probe used only by the concurrency ablation."""

    @property
    def name(self) -> str:
        return "delayed_read"

    @property
    def description(self) -> str:
        return "Return a value after a fixed delay."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]}

    @property
    def is_read_only(self) -> bool:
        return True

    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds

    def execute(self, params: dict[str, Any]) -> ToolResult:
        time.sleep(self.delay_seconds)
        return ToolResult(output=str(params["value"]))


def run_parallel_read_only_ablation(
    *,
    trials: int = 3,
    calls_per_trial: int = 4,
    delay_seconds: float = 0.02,
) -> dict[str, Any]:
    """Compare AgentLoop sequential and bounded-parallel read-only execution."""
    if trials <= 0 or calls_per_trial <= 1 or delay_seconds <= 0:
        raise ValueError("trials, calls_per_trial, and delay_seconds must be positive; calls_per_trial must exceed one.")

    modes = {
        "sequential": 1,
        "parallel_read_only": calls_per_trial,
    }
    results = {
        name: _run_mode(
            max_parallel_read_only_calls=limit,
            trials=trials,
            calls_per_trial=calls_per_trial,
            delay_seconds=delay_seconds,
        )
        for name, limit in modes.items()
    }
    sequential_ms = results["sequential"]["mean_duration_ms"]
    parallel_ms = results["parallel_read_only"]["mean_duration_ms"]
    return {
        "schema_version": 1,
        "experiment": "parallel_read_only_tool_ablation",
        "api_required": False,
        "parameters": {
            "trials": trials,
            "calls_per_trial": calls_per_trial,
            "delay_seconds": delay_seconds,
        },
        "modes": results,
        "comparison": {
            "latency_speedup": round(sequential_ms / parallel_ms, 3) if parallel_ms else None,
            "success_rate_delta": round(
                results["parallel_read_only"]["success_rate"] - results["sequential"]["success_rate"], 4,
            ),
            "token_delta": 0,
            "error_rate_delta": round(
                results["parallel_read_only"]["tool_error_rate"] - results["sequential"]["tool_error_rate"], 4,
            ),
        },
    }


def write_parallel_read_only_ablation(report: dict[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "parallel_read_only_ablation.json"
    markdown_path = output / "parallel_read_only_ablation.md"
    import json

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Parallel Read-Only Tool Ablation", "", "| Mode | Success | Mean latency | Tokens | Tool error rate |", "| --- | ---: | ---: | ---: | ---: |"]
    for name, metrics in report["modes"].items():
        lines.append(
            f"| {name} | {metrics['success_rate']:.2%} | {metrics['mean_duration_ms']} ms | "
            f"{metrics['mean_tokens']} | {metrics['tool_error_rate']:.2%} |"
        )
    lines.extend(["", f"Latency speedup: {report['comparison']['latency_speedup']}x", ""])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, markdown_path


def _run_mode(
    *,
    max_parallel_read_only_calls: int,
    trials: int,
    calls_per_trial: int,
    delay_seconds: float,
) -> dict[str, Any]:
    durations: list[float] = []
    successes = 0
    error_count = 0
    total_calls = 0
    for trial in range(trials):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ToolRegistry()
            registry.register(DelayedReadTool(delay_seconds))
            config = Config(
                permission_mode=PermissionMode.AUTO,
                max_parallel_read_only_calls=max_parallel_read_only_calls,
            )
            tracer = TraceRecorder(trace_dir=tmpdir)
            agent = AgentLoop(config=config, registry=registry, client=object(), output=StringIO(), tracer=tracer)
            calls = [
                {"id": f"trial-{trial}-{index}", "name": "delayed_read", "input": {"value": index}}
                for index in range(calls_per_trial)
            ]
            started_at = time.perf_counter()
            agent._execute_tool_calls(calls, turn=1, run_id=f"trial-{trial}")
            durations.append((time.perf_counter() - started_at) * 1000)
            results = agent.context.messages[-1]["content"]
            successes += int([item["content"] for item in results] == [str(index) for index in range(calls_per_trial)])
            trace_events = [
                event for path in Path(tmpdir).glob("*.jsonl")
                for event in _read_jsonl(path)
            ]
            error_count += sum(event.get("status") == "error" for event in trace_events)
            total_calls += len(trace_events)
    return {
        "trials": trials,
        "success_rate": round(successes / trials, 4),
        "mean_duration_ms": round(statistics.mean(durations), 3),
        "mean_tokens": 0,
        "tool_error_rate": round(error_count / total_calls, 4) if total_calls else 0.0,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    import json

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
