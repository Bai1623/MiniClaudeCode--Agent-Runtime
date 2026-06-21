"""Tests for Git worktree inspection."""

from __future__ import annotations

import unittest
from pathlib import Path

from miniclaudecode.git_workflow.worktree import (
    GitCommandResult,
    GitWorkflowError,
    WorktreeInspector,
)

GIT = ("git", "-c", "core.quotepath=false")


class FakeGitRunner:
    def __init__(self, results: dict[tuple[str, ...], GitCommandResult]) -> None:
        self.results = results
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command: list[str], cwd: Path) -> GitCommandResult:
        self.calls.append((command, cwd))
        return self.results[tuple(command)]


def ok(command: list[str], stdout: str = "") -> GitCommandResult:
    return GitCommandResult(command=command, returncode=0, stdout=stdout)


class TestWorktreeInspector(unittest.TestCase):
    def make_runner(self, status_output: str = "") -> FakeGitRunner:
        return FakeGitRunner({
            (*GIT, "rev-parse", "--is-inside-work-tree"): ok(
                [*GIT, "rev-parse", "--is-inside-work-tree"],
                "true\n",
            ),
            (*GIT, "status", "--porcelain=v1", "-b"): ok(
                [*GIT, "status", "--porcelain=v1", "-b"],
                status_output,
            ),
            (*GIT, "diff", "--stat"): ok(
                [*GIT, "diff", "--stat"],
                " file.py | 2 +-\n",
            ),
            (*GIT, "diff", "--name-only"): ok(
                [*GIT, "diff", "--name-only"],
                "file.py\nREADME.md\n",
            ),
            (*GIT, "diff", "--cached", "--name-only"): ok(
                [*GIT, "diff", "--cached", "--name-only"],
                "staged.py\n",
            ),
        })

    def test_parse_clean_status(self):
        inspector = WorktreeInspector(runner=self.make_runner("## master...origin/master\n"))

        status = inspector.get_status()

        self.assertEqual(status.branch, "master")
        self.assertFalse(status.is_dirty)
        self.assertEqual(status.changed_files, [])
        self.assertEqual(status.untracked_files, [])
        self.assertEqual(status.staged_files, [])

    def test_parse_changed_untracked_and_staged_files(self):
        output = "\n".join([
            "## feature/test",
            " M modified.py",
            "A  staged_new.py",
            "MM both.py",
            "?? new_file.py",
        ])
        inspector = WorktreeInspector(runner=self.make_runner(output))

        status = inspector.get_status()

        self.assertEqual(status.branch, "feature/test")
        self.assertTrue(status.is_dirty)
        self.assertEqual(status.changed_files, ["both.py", "modified.py"])
        self.assertEqual(status.untracked_files, ["new_file.py"])
        self.assertEqual(status.staged_files, ["both.py", "staged_new.py"])

    def test_parse_renamed_staged_file_uses_new_path(self):
        output = "\n".join([
            "## master",
            "R  old.py -> new.py",
        ])
        inspector = WorktreeInspector(runner=self.make_runner(output))

        status = inspector.get_status()

        self.assertEqual(status.staged_files, ["new.py"])

    def test_get_diff_stat(self):
        inspector = WorktreeInspector(runner=self.make_runner())

        self.assertEqual(inspector.get_diff_stat(), " file.py | 2 +-\n")

    def test_get_changed_files(self):
        inspector = WorktreeInspector(runner=self.make_runner())

        self.assertEqual(inspector.get_changed_files(), ["file.py", "README.md"])

    def test_get_staged_files(self):
        inspector = WorktreeInspector(runner=self.make_runner())

        self.assertEqual(inspector.get_staged_files(), ["staged.py"])

    def test_non_git_repo_raises_clear_error(self):
        runner = FakeGitRunner({
            (*GIT, "rev-parse", "--is-inside-work-tree"): GitCommandResult(
                command=[*GIT, "rev-parse", "--is-inside-work-tree"],
                returncode=128,
                stderr="fatal: not a git repository",
            )
        })
        inspector = WorktreeInspector(runner=runner)

        with self.assertRaisesRegex(GitWorkflowError, "not a git repository"):
            inspector.ensure_git_repo()


if __name__ == "__main__":
    unittest.main()
