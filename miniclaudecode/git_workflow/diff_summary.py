"""Structured summaries for Git diffs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from miniclaudecode.git_workflow.worktree import (
    GitCommandResult,
    GitRunner,
    GitWorkflowError,
    _decode_git_output,
)


@dataclass(frozen=True)
class FileChange:
    path: str
    change_type: str
    additions: int
    deletions: int


@dataclass(frozen=True)
class DiffSummary:
    files: list[FileChange]
    total_additions: int
    total_deletions: int

    @property
    def has_changes(self) -> bool:
        return bool(self.files)

    def to_markdown(self) -> str:
        if not self.files:
            return "## Diff Summary\n\nNo tracked file changes."

        lines = [
            "## Diff Summary",
            "",
            f"Files changed: {len(self.files)}",
            f"Additions: {self.total_additions}",
            f"Deletions: {self.total_deletions}",
            "",
            "| File | Type | + | - |",
            "| --- | --- | ---: | ---: |",
        ]
        for change in self.files:
            lines.append(
                f"| {change.path} | {change.change_type} | {change.additions} | {change.deletions} |"
            )
        return "\n".join(lines)


class DiffSummaryCollector:
    """Collects and parses git diff statistics."""

    def __init__(self, repo_dir: str | Path = ".", runner: GitRunner | None = None) -> None:
        self.repo_dir = Path(repo_dir)
        self.runner = runner or self._default_runner

    def get_summary(self, cached: bool = False) -> DiffSummary:
        command = ["git", "-c", "core.quotepath=false", "diff"]
        if cached:
            command.append("--cached")
        command.append("--numstat")

        result = self.runner(command, self.repo_dir)
        if result.returncode != 0:
            label = "git diff --cached --numstat" if cached else "git diff --numstat"
            raise GitWorkflowError(result.stderr.strip() or f"{label} failed")
        return parse_numstat(result.stdout)

    @staticmethod
    def _default_runner(command: list[str], cwd: Path) -> GitCommandResult:
        import subprocess

        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            timeout=30,
        )
        return GitCommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=_decode_git_output(completed.stdout),
            stderr=_decode_git_output(completed.stderr),
        )


def parse_numstat(output: str) -> DiffSummary:
    files: list[FileChange] = []
    total_additions = 0
    total_deletions = 0

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split("\t")
        if len(parts) < 3:
            raise GitWorkflowError(f"Invalid git numstat line: {raw_line}")

        additions_raw, deletions_raw, path = parts[0], parts[1], "\t".join(parts[2:])
        if additions_raw == "-" and deletions_raw == "-":
            change = FileChange(
                path=_normalize_numstat_path(path),
                change_type="binary",
                additions=0,
                deletions=0,
            )
            files.append(change)
            continue

        try:
            additions = int(additions_raw)
            deletions = int(deletions_raw)
        except ValueError as exc:
            raise GitWorkflowError(f"Invalid git numstat counts: {raw_line}") from exc

        total_additions += additions
        total_deletions += deletions
        files.append(
            FileChange(
                path=_normalize_numstat_path(path),
                change_type=_infer_change_type(additions, deletions),
                additions=additions,
                deletions=deletions,
            )
        )

    return DiffSummary(
        files=files,
        total_additions=total_additions,
        total_deletions=total_deletions,
    )


def _infer_change_type(additions: int, deletions: int) -> str:
    if additions > 0 and deletions == 0:
        return "added"
    if additions == 0 and deletions > 0:
        return "deleted"
    return "modified"


def _normalize_numstat_path(path: str) -> str:
    if " => " not in path:
        return path
    if "}" not in path:
        return path
    return path.split(" => ", 1)[1].rstrip("}")
