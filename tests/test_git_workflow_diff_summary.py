"""Tests for Git diff summaries."""

from __future__ import annotations

import unittest
from pathlib import Path

from miniclaudecode.git_workflow.diff_summary import (
    DiffSummaryCollector,
    parse_numstat,
)
from miniclaudecode.git_workflow.worktree import GitCommandResult, GitWorkflowError

GIT = ["git", "-c", "core.quotepath=false"]


class FakeGitRunner:
    def __init__(self, results: dict[tuple[str, ...], GitCommandResult]) -> None:
        self.results = results
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command: list[str], cwd: Path) -> GitCommandResult:
        self.calls.append((command, cwd))
        return self.results[tuple(command)]


def result(command: list[str], stdout: str = "", returncode: int = 0, stderr: str = "") -> GitCommandResult:
    return GitCommandResult(
        command=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class TestDiffSummary(unittest.TestCase):
    def test_parse_regular_file_changes(self):
        summary = parse_numstat("12\t3\tminiclaudecode/cli.py\n4\t0\ttests/test_cli.py\n")

        self.assertTrue(summary.has_changes)
        self.assertEqual(summary.total_additions, 16)
        self.assertEqual(summary.total_deletions, 3)
        self.assertEqual(summary.files[0].path, "miniclaudecode/cli.py")
        self.assertEqual(summary.files[0].change_type, "modified")
        self.assertEqual(summary.files[1].change_type, "added")

    def test_parse_binary_file_change(self):
        summary = parse_numstat("-\t-\tassets/logo.png\n")

        self.assertEqual(summary.total_additions, 0)
        self.assertEqual(summary.total_deletions, 0)
        self.assertEqual(summary.files[0].change_type, "binary")
        self.assertEqual(summary.files[0].path, "assets/logo.png")

    def test_parse_empty_diff(self):
        summary = parse_numstat("")

        self.assertFalse(summary.has_changes)
        self.assertEqual(summary.total_additions, 0)
        self.assertEqual(summary.total_deletions, 0)
        self.assertEqual(summary.files, [])

    def test_parse_invalid_numstat_line_raises_clear_error(self):
        with self.assertRaisesRegex(GitWorkflowError, "Invalid git numstat line"):
            parse_numstat("bad line")

    def test_markdown_summary_includes_totals_and_files(self):
        summary = parse_numstat("2\t1\tfile.py\n")

        markdown = summary.to_markdown()

        self.assertIn("Files changed: 1", markdown)
        self.assertIn("Additions: 2", markdown)
        self.assertIn("Deletions: 1", markdown)
        self.assertIn("| file.py | modified | 2 | 1 |", markdown)

    def test_empty_markdown_summary(self):
        self.assertEqual(
            parse_numstat("").to_markdown(),
            "## Diff Summary\n\nNo tracked file changes.",
        )

    def test_collector_runs_numstat(self):
        command = [*GIT, "diff", "--numstat"]
        runner = FakeGitRunner({
            tuple(command): result(command, "1\t0\tfile.py\n"),
        })
        collector = DiffSummaryCollector(repo_dir=".", runner=runner)

        summary = collector.get_summary()

        self.assertEqual(summary.total_additions, 1)
        self.assertEqual(runner.calls[0][0], command)

    def test_collector_runs_cached_numstat(self):
        command = [*GIT, "diff", "--cached", "--numstat"]
        runner = FakeGitRunner({
            tuple(command): result(command, "0\t2\tfile.py\n"),
        })
        collector = DiffSummaryCollector(repo_dir=".", runner=runner)

        summary = collector.get_summary(cached=True)

        self.assertEqual(summary.total_deletions, 2)
        self.assertEqual(runner.calls[0][0], command)

    def test_collector_command_failure_raises_clear_error(self):
        command = [*GIT, "diff", "--numstat"]
        runner = FakeGitRunner({
            tuple(command): result(command, returncode=128, stderr="fatal: not a git repository"),
        })
        collector = DiffSummaryCollector(runner=runner)

        with self.assertRaisesRegex(GitWorkflowError, "not a git repository"):
            collector.get_summary()


if __name__ == "__main__":
    unittest.main()
