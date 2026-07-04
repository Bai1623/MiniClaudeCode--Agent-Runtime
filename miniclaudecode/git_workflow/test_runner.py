"""Test command execution for Git workflow reports."""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

DEFAULT_TEST_COMMAND = [sys.executable, "-m", "unittest", "discover"]
DEFAULT_OUTPUT_LIMIT = 12_000


@dataclass(frozen=True)
class TestRunResult:
    command: list[str]
    returncode: int
    duration_ms: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def to_markdown(self) -> str:
        status = "passed" if self.passed else "failed"
        command = " ".join(self.command)
        lines = [
            "## Test Result",
            "",
            f"Command: `{command}`",
            f"Status: {status}",
            f"Return code: {self.returncode}",
            f"Duration: {self.duration_ms} ms",
        ]
        if self.timed_out:
            lines.append("Timed out: true")
        if self.stdout:
            lines.extend(["", "Stdout:", "```text", self.stdout, "```"])
        if self.stderr:
            lines.extend(["", "Stderr:", "```text", self.stderr, "```"])
        return "\n".join(lines)


TestCommandRunner = Callable[[list[str], Path, int], TestRunResult]


class TestRunner:
    """Runs deterministic test commands and records structured results."""

    def __init__(
        self,
        repo_dir: str | Path = ".",
        runner: TestCommandRunner | None = None,
        output_limit: int = DEFAULT_OUTPUT_LIMIT,
    ) -> None:
        self.repo_dir = Path(repo_dir)
        self.runner = runner or self._default_runner
        self.output_limit = output_limit

    def run(
        self,
        command: list[str] | None = None,
        timeout_seconds: int = 120,
    ) -> TestRunResult:
        command = command or DEFAULT_TEST_COMMAND
        result = self.runner(command, self.repo_dir, timeout_seconds)
        return TestRunResult(
            command=result.command,
            returncode=result.returncode,
            duration_ms=result.duration_ms,
            stdout=_truncate_output(result.stdout, self.output_limit),
            stderr=_truncate_output(result.stderr, self.output_limit),
            timed_out=result.timed_out,
        )

    @staticmethod
    def _default_runner(command: list[str], cwd: Path, timeout_seconds: int) -> TestRunResult:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
            )
            return TestRunResult(
                command=command,
                returncode=completed.returncode,
                duration_ms=_elapsed_ms(started),
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        except subprocess.TimeoutExpired as exc:
            return TestRunResult(
                command=command,
                returncode=124,
                duration_ms=_elapsed_ms(started),
                stdout=_decode_timeout_output(exc.stdout),
                stderr=_decode_timeout_output(exc.stderr)
                or f"Command timed out after {timeout_seconds}s.",
                timed_out=True,
            )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _truncate_output(output: str, max_chars: int) -> str:
    if len(output) <= max_chars:
        return output
    head_chars = max_chars // 2
    tail_chars = max_chars - head_chars
    return (
        output[:head_chars]
        + "\n\n... output truncated ...\n"
        + f"Original length: {len(output)} chars.\n"
        + f"Showing first {head_chars} chars and last {tail_chars} chars.\n\n"
        + output[-tail_chars:]
    )


def _decode_timeout_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode(errors="replace")
    return output
