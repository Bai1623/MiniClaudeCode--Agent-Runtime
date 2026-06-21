"""Worktree inspection helpers for Git workflow reports."""

from __future__ import annotations

import locale
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class GitCommandResult:
    command: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class WorktreeStatus:
    branch: str
    changed_files: list[str]
    untracked_files: list[str]
    staged_files: list[str]
    is_dirty: bool


GitRunner = Callable[[list[str], Path], GitCommandResult]


class GitWorkflowError(RuntimeError):
    pass


class WorktreeInspector:
    """Reads and parses local Git worktree state."""

    def __init__(self, repo_dir: str | Path = ".", runner: GitRunner | None = None) -> None:
        self.repo_dir = Path(repo_dir)
        self.runner = runner or self._default_runner

    def ensure_git_repo(self) -> None:
        result = self.runner(["git", "-c", "core.quotepath=false", "rev-parse", "--is-inside-work-tree"], self.repo_dir)
        if result.returncode != 0 or result.stdout.strip() != "true":
            message = result.stderr.strip() or "Not inside a git worktree."
            raise GitWorkflowError(message)

    def get_status(self) -> WorktreeStatus:
        self.ensure_git_repo()
        result = self.runner(["git", "-c", "core.quotepath=false", "status", "--porcelain=v1", "-b"], self.repo_dir)
        if result.returncode != 0:
            raise GitWorkflowError(result.stderr.strip() or "git status failed")
        return self._parse_status(result.stdout)

    def get_diff_stat(self) -> str:
        self.ensure_git_repo()
        result = self.runner(["git", "-c", "core.quotepath=false", "diff", "--stat"], self.repo_dir)
        if result.returncode != 0:
            raise GitWorkflowError(result.stderr.strip() or "git diff --stat failed")
        return result.stdout

    def get_changed_files(self) -> list[str]:
        self.ensure_git_repo()
        result = self.runner(["git", "-c", "core.quotepath=false", "diff", "--name-only"], self.repo_dir)
        if result.returncode != 0:
            raise GitWorkflowError(result.stderr.strip() or "git diff --name-only failed")
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def get_staged_files(self) -> list[str]:
        self.ensure_git_repo()
        result = self.runner(["git", "-c", "core.quotepath=false", "diff", "--cached", "--name-only"], self.repo_dir)
        if result.returncode != 0:
            raise GitWorkflowError(result.stderr.strip() or "git diff --cached --name-only failed")
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    @staticmethod
    def _parse_status(output: str) -> WorktreeStatus:
        branch = ""
        changed: set[str] = set()
        untracked: set[str] = set()
        staged: set[str] = set()

        for raw_line in output.splitlines():
            line = raw_line.rstrip()
            if not line:
                continue
            if line.startswith("## "):
                branch = WorktreeInspector._parse_branch(line)
                continue

            status = line[:2]
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]

            index_status = status[0]
            worktree_status = status[1]

            if status == "??":
                untracked.add(path)
                continue

            if index_status != " ":
                staged.add(path)
            if worktree_status != " ":
                changed.add(path)

        dirty = bool(changed or untracked or staged)
        return WorktreeStatus(
            branch=branch,
            changed_files=sorted(changed),
            untracked_files=sorted(untracked),
            staged_files=sorted(staged),
            is_dirty=dirty,
        )

    @staticmethod
    def _parse_branch(line: str) -> str:
        branch_info = line[3:].strip()
        if "..." in branch_info:
            return branch_info.split("...", 1)[0]
        return branch_info

    @staticmethod
    def _default_runner(command: list[str], cwd: Path) -> GitCommandResult:
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


def _decode_git_output(output: bytes) -> str:
    for encoding in ("utf-8", locale.getpreferredencoding(False), "gbk"):
        try:
            return output.decode(encoding)
        except UnicodeDecodeError:
            continue
    return output.decode("utf-8", errors="replace")
