"""High-level Git workflow analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from miniclaudecode.git_workflow.commit_message import CommitMessageGenerator
from miniclaudecode.git_workflow.diff_summary import DiffSummary, DiffSummaryCollector, FileChange
from miniclaudecode.git_workflow.test_runner import TestRunner, TestRunResult
from miniclaudecode.git_workflow.worktree import WorktreeInspector, WorktreeStatus


@dataclass(frozen=True)
class GitWorkflowReport:
    status: WorktreeStatus
    diff_summary: DiffSummary
    test_result: TestRunResult | None
    commit_message: str

    def to_markdown(self) -> str:
        lines = [
            "## Git Workflow Report",
            "",
            "### Worktree",
            "",
            f"Branch: {self.status.branch or 'unknown'}",
            f"Dirty: {str(self.status.is_dirty).lower()}",
            f"Changed files: {len(self.status.changed_files)}",
            f"Staged files: {len(self.status.staged_files)}",
            f"Untracked files: {len(self.status.untracked_files)}",
        ]

        if self.status.changed_files:
            lines.extend(["", "Changed:", *[f"- {path}" for path in self.status.changed_files]])
        if self.status.staged_files:
            lines.extend(["", "Staged:", *[f"- {path}" for path in self.status.staged_files]])
        if self.status.untracked_files:
            lines.extend(["", "Untracked:", *[f"- {path}" for path in self.status.untracked_files]])

        lines.extend(["", self.diff_summary.to_markdown()])

        if self.test_result is not None:
            lines.extend(["", self.test_result.to_markdown()])

        lines.extend([
            "",
            "## Suggested Commit Message",
            "",
            "```text",
            self.commit_message,
            "```",
        ])
        return "\n".join(lines)


class GitWorkflow:
    """Coordinates worktree, diff, test, and commit-message analysis."""

    def __init__(
        self,
        repo_dir: str | Path = ".",
        worktree: WorktreeInspector | None = None,
        diff_collector: DiffSummaryCollector | None = None,
        test_runner: TestRunner | None = None,
        commit_message_generator: CommitMessageGenerator | None = None,
    ) -> None:
        self.repo_dir = Path(repo_dir)
        self.worktree = worktree or WorktreeInspector(self.repo_dir)
        self.diff_collector = diff_collector or DiffSummaryCollector(self.repo_dir)
        self.test_runner = test_runner or TestRunner(self.repo_dir)
        self.commit_message_generator = commit_message_generator or CommitMessageGenerator()

    def analyze(
        self,
        run_tests: bool = True,
        test_command: list[str] | None = None,
        test_timeout_seconds: int = 120,
        user_summary: str | None = None,
    ) -> GitWorkflowReport:
        status = self.worktree.get_status()
        diff_summary = merge_diff_summaries([
            self.diff_collector.get_summary(cached=False),
            self.diff_collector.get_summary(cached=True),
        ])
        test_result = None
        if run_tests:
            test_result = self.test_runner.run(
                command=test_command,
                timeout_seconds=test_timeout_seconds,
            )
        commit_message = self.commit_message_generator.generate(
            diff_summary=diff_summary,
            test_result=test_result,
            user_summary=user_summary,
        )
        return GitWorkflowReport(
            status=status,
            diff_summary=diff_summary,
            test_result=test_result,
            commit_message=commit_message,
        )


def merge_diff_summaries(summaries: list[DiffSummary]) -> DiffSummary:
    changes: dict[str, FileChange] = {}

    for summary in summaries:
        for change in summary.files:
            existing = changes.get(change.path)
            if existing is None:
                changes[change.path] = change
                continue

            changes[change.path] = FileChange(
                path=change.path,
                change_type=_merge_change_type(existing.change_type, change.change_type),
                additions=existing.additions + change.additions,
                deletions=existing.deletions + change.deletions,
            )

    files = sorted(changes.values(), key=lambda item: item.path)
    return DiffSummary(
        files=files,
        total_additions=sum(change.additions for change in files),
        total_deletions=sum(change.deletions for change in files),
    )


def _merge_change_type(left: str, right: str) -> str:
    if "binary" in {left, right}:
        return "binary"
    if left == right:
        return left
    return "modified"
