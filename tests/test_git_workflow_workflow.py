"""Tests for high-level Git workflow analysis."""

from __future__ import annotations

import unittest

from miniclaudecode.git_workflow.diff_summary import DiffSummary, FileChange
from miniclaudecode.git_workflow.test_runner import TestRunResult
from miniclaudecode.git_workflow.workflow import GitWorkflow, merge_diff_summaries
from miniclaudecode.git_workflow.worktree import WorktreeStatus


class FakeWorktree:
    def __init__(self, status: WorktreeStatus) -> None:
        self.status = status
        self.called = False

    def get_status(self) -> WorktreeStatus:
        self.called = True
        return self.status


class FakeDiffCollector:
    def __init__(self, unstaged: DiffSummary, staged: DiffSummary) -> None:
        self.unstaged = unstaged
        self.staged = staged
        self.calls: list[bool] = []

    def get_summary(self, cached: bool = False) -> DiffSummary:
        self.calls.append(cached)
        return self.staged if cached else self.unstaged


class FakeTestRunner:
    def __init__(self, result: TestRunResult) -> None:
        self.result = result
        self.calls: list[tuple[list[str] | None, int]] = []

    def run(
        self,
        command: list[str] | None = None,
        timeout_seconds: int = 120,
    ) -> TestRunResult:
        self.calls.append((command, timeout_seconds))
        return self.result


class FakeCommitMessageGenerator:
    def __init__(self) -> None:
        self.calls: list[tuple[DiffSummary, TestRunResult | None, str | None]] = []

    def generate(
        self,
        diff_summary: DiffSummary,
        test_result: TestRunResult | None = None,
        user_summary: str | None = None,
    ) -> str:
        self.calls.append((diff_summary, test_result, user_summary))
        return user_summary or "Generated commit message"


def diff(*changes: FileChange) -> DiffSummary:
    files = list(changes)
    return DiffSummary(
        files=files,
        total_additions=sum(change.additions for change in files),
        total_deletions=sum(change.deletions for change in files),
    )


def status(dirty: bool = True) -> WorktreeStatus:
    return WorktreeStatus(
        branch="master",
        changed_files=["miniclaudecode/cli.py"] if dirty else [],
        untracked_files=["new.py"] if dirty else [],
        staged_files=["tests/test_cli.py"] if dirty else [],
        is_dirty=dirty,
    )


def test_result(returncode: int = 0) -> TestRunResult:
    return TestRunResult(
        command=["python", "-m", "unittest", "discover"],
        returncode=returncode,
        duration_ms=20,
        stdout="OK" if returncode == 0 else "",
        stderr="" if returncode == 0 else "FAILED",
    )


class TestGitWorkflow(unittest.TestCase):
    def test_analyze_collects_status_diff_tests_and_commit_message(self):
        worktree = FakeWorktree(status())
        diff_collector = FakeDiffCollector(
            unstaged=diff(FileChange("miniclaudecode/cli.py", "modified", 5, 1)),
            staged=diff(FileChange("tests/test_cli.py", "added", 3, 0)),
        )
        tests = FakeTestRunner(test_result())
        generator = FakeCommitMessageGenerator()
        workflow = GitWorkflow(
            worktree=worktree,
            diff_collector=diff_collector,
            test_runner=tests,
            commit_message_generator=generator,
        )

        report = workflow.analyze(user_summary="Update git workflow")

        self.assertTrue(worktree.called)
        self.assertEqual(diff_collector.calls, [False, True])
        self.assertEqual(tests.calls, [(None, 120)])
        self.assertEqual(report.status.branch, "master")
        self.assertEqual(report.diff_summary.total_additions, 8)
        self.assertEqual(report.diff_summary.total_deletions, 1)
        self.assertEqual(report.test_result, tests.result)
        self.assertEqual(report.commit_message, "Update git workflow")
        self.assertEqual(generator.calls[0][2], "Update git workflow")

    def test_analyze_can_skip_tests(self):
        tests = FakeTestRunner(test_result())
        generator = FakeCommitMessageGenerator()
        workflow = GitWorkflow(
            worktree=FakeWorktree(status(False)),
            diff_collector=FakeDiffCollector(diff(), diff()),
            test_runner=tests,
            commit_message_generator=generator,
        )

        report = workflow.analyze(run_tests=False)

        self.assertEqual(tests.calls, [])
        self.assertIsNone(report.test_result)
        self.assertIsNone(generator.calls[0][1])

    def test_analyze_passes_custom_test_command_and_timeout(self):
        tests = FakeTestRunner(test_result())
        workflow = GitWorkflow(
            worktree=FakeWorktree(status()),
            diff_collector=FakeDiffCollector(diff(), diff()),
            test_runner=tests,
            commit_message_generator=FakeCommitMessageGenerator(),
        )

        workflow.analyze(test_command=["python", "-m", "compileall"], test_timeout_seconds=5)

        self.assertEqual(tests.calls, [(["python", "-m", "compileall"], 5)])

    def test_failed_test_result_is_preserved(self):
        failed = test_result(returncode=1)
        workflow = GitWorkflow(
            worktree=FakeWorktree(status()),
            diff_collector=FakeDiffCollector(diff(), diff()),
            test_runner=FakeTestRunner(failed),
            commit_message_generator=FakeCommitMessageGenerator(),
        )

        report = workflow.analyze()

        self.assertFalse(report.test_result.passed)
        self.assertEqual(report.test_result.stderr, "FAILED")

    def test_report_markdown_includes_key_sections(self):
        report = GitWorkflow(
            worktree=FakeWorktree(status()),
            diff_collector=FakeDiffCollector(
                diff(FileChange("miniclaudecode/cli.py", "modified", 1, 0)),
                diff(),
            ),
            test_runner=FakeTestRunner(test_result()),
            commit_message_generator=FakeCommitMessageGenerator(),
        ).analyze()

        markdown = report.to_markdown()

        self.assertIn("## Git Workflow Report", markdown)
        self.assertIn("Branch: master", markdown)
        self.assertIn("Untracked:", markdown)
        self.assertIn("## Diff Summary", markdown)
        self.assertIn("## Test Result", markdown)
        self.assertIn("## Suggested Commit Message", markdown)

    def test_report_can_be_converted_to_task_memory(self):
        report = GitWorkflow(
            worktree=FakeWorktree(status()),
            diff_collector=FakeDiffCollector(
                diff(FileChange("miniclaudecode/cli.py", "modified", 1, 0)),
                diff(),
            ),
            test_runner=FakeTestRunner(test_result()),
            commit_message_generator=FakeCommitMessageGenerator(),
        ).analyze()

        memory = report.to_task_memory("git-workflow-test")

        self.assertEqual(memory.id, "git-workflow-test")
        self.assertEqual(memory.result, "passed")
        self.assertIn("miniclaudecode/cli.py", memory.changed_files)
        self.assertIn("python -m unittest discover", memory.tests)
        self.assertIn("Generated commit message", memory.summary)

    def test_merge_diff_summaries_combines_same_path(self):
        merged = merge_diff_summaries([
            diff(FileChange("file.py", "modified", 2, 1)),
            diff(FileChange("file.py", "modified", 3, 4)),
        ])

        self.assertEqual(len(merged.files), 1)
        self.assertEqual(merged.files[0].additions, 5)
        self.assertEqual(merged.files[0].deletions, 5)
        self.assertEqual(merged.total_additions, 5)
        self.assertEqual(merged.total_deletions, 5)


if __name__ == "__main__":
    unittest.main()
