"""Tests for commit message generation."""

from __future__ import annotations

import unittest

from miniclaudecode.git_workflow.commit_message import CommitMessageGenerator
from miniclaudecode.git_workflow.diff_summary import DiffSummary, FileChange
from miniclaudecode.git_workflow.test_runner import TestRunResult


def summary(files: list[FileChange]) -> DiffSummary:
    return DiffSummary(
        files=files,
        total_additions=sum(file.additions for file in files),
        total_deletions=sum(file.deletions for file in files),
    )


def passed_tests() -> TestRunResult:
    return TestRunResult(
        command=["python", "-m", "unittest", "discover"],
        returncode=0,
        duration_ms=10,
        stdout="OK",
        stderr="",
    )


class TestCommitMessageGenerator(unittest.TestCase):
    def test_source_and_tests_subject(self):
        diff = summary([
            FileChange("miniclaudecode/git_workflow/workflow.py", "added", 10, 0),
            FileChange("tests/test_git_workflow_workflow.py", "added", 8, 0),
        ])

        message = CommitMessageGenerator().generate(diff, passed_tests())

        self.assertTrue(message.startswith("Update implementation and tests"))
        self.assertIn("- Update source files: miniclaudecode/git_workflow/workflow.py", message)
        self.assertIn("- Update tests: tests/test_git_workflow_workflow.py", message)
        self.assertIn("- Tests: `python -m unittest discover` passed", message)

    def test_docs_only_subject(self):
        diff = summary([
            FileChange("docs/Git Workflow 工程闭环.md", "modified", 3, 1),
        ])

        message = CommitMessageGenerator().generate(diff)

        self.assertTrue(message.startswith("Update documentation"))
        self.assertIn("- Update documentation: docs/Git Workflow 工程闭环.md", message)

    def test_tests_only_subject(self):
        diff = summary([
            FileChange("tests/test_cli.py", "modified", 2, 2),
        ])

        message = CommitMessageGenerator().generate(diff)

        self.assertTrue(message.startswith("Update tests"))

    def test_user_summary_overrides_subject(self):
        diff = summary([
            FileChange("miniclaudecode/cli.py", "modified", 4, 1),
        ])

        message = CommitMessageGenerator().generate(diff, user_summary="  Add git summary CLI  ")

        self.assertTrue(message.startswith("Add git summary CLI"))

    def test_failed_tests_are_recorded(self):
        diff = summary([
            FileChange("miniclaudecode/cli.py", "modified", 4, 1),
        ])
        failed = TestRunResult(
            command=["python", "-m", "unittest", "discover"],
            returncode=1,
            duration_ms=10,
            stdout="",
            stderr="FAILED",
        )

        message = CommitMessageGenerator().generate(diff, failed)

        self.assertIn("- Tests: `python -m unittest discover` failed", message)

    def test_timeout_tests_are_recorded(self):
        diff = summary([
            FileChange("miniclaudecode/cli.py", "modified", 4, 1),
        ])
        timed_out = TestRunResult(
            command=["python", "-m", "unittest", "discover"],
            returncode=124,
            duration_ms=1000,
            stdout="",
            stderr="timeout",
            timed_out=True,
        )

        message = CommitMessageGenerator().generate(diff, timed_out)

        self.assertIn("- Tests: `python -m unittest discover` timed out", message)

    def test_no_changes_has_fallback_message(self):
        message = CommitMessageGenerator().generate(summary([]))

        self.assertEqual(
            message,
            "No code changes detected\n\n- No tracked file changes were found",
        )

    def test_message_has_no_leading_blank_line(self):
        diff = summary([
            FileChange("miniclaudecode/cli.py", "modified", 1, 0),
        ])

        message = CommitMessageGenerator().generate(diff)

        self.assertFalse(message.startswith("\n"))


if __name__ == "__main__":
    unittest.main()
