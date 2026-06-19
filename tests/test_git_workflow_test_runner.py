"""Tests for Git workflow test command execution."""

from __future__ import annotations

import unittest
from pathlib import Path

from miniclaudecode.git_workflow.test_runner import (
    DEFAULT_TEST_COMMAND,
    TestRunner,
    TestRunResult,
)


class FakeTestCommandRunner:
    def __init__(self, result: TestRunResult) -> None:
        self.result = result
        self.calls: list[tuple[list[str], Path, int]] = []

    def __call__(self, command: list[str], cwd: Path, timeout_seconds: int) -> TestRunResult:
        self.calls.append((command, cwd, timeout_seconds))
        return self.result


class TestGitWorkflowTestRunner(unittest.TestCase):
    def test_successful_command_passes(self):
        fake = FakeTestCommandRunner(TestRunResult(
            command=DEFAULT_TEST_COMMAND,
            returncode=0,
            duration_ms=12,
            stdout="OK\n",
            stderr="",
        ))
        runner = TestRunner(repo_dir=".", runner=fake)

        result = runner.run()

        self.assertTrue(result.passed)
        self.assertEqual(result.command, DEFAULT_TEST_COMMAND)
        self.assertEqual(fake.calls[0][0], DEFAULT_TEST_COMMAND)

    def test_failed_command_does_not_pass(self):
        fake = FakeTestCommandRunner(TestRunResult(
            command=["python", "-m", "unittest", "bad"],
            returncode=1,
            duration_ms=20,
            stdout="",
            stderr="FAILED\n",
        ))
        runner = TestRunner(runner=fake)

        result = runner.run(["python", "-m", "unittest", "bad"])

        self.assertFalse(result.passed)
        self.assertEqual(result.stderr, "FAILED\n")

    def test_timeout_result_does_not_pass(self):
        fake = FakeTestCommandRunner(TestRunResult(
            command=["slow"],
            returncode=124,
            duration_ms=1000,
            stdout="",
            stderr="Command timed out.",
            timed_out=True,
        ))
        runner = TestRunner(runner=fake)

        result = runner.run(["slow"], timeout_seconds=1)

        self.assertFalse(result.passed)
        self.assertTrue(result.timed_out)
        self.assertEqual(fake.calls[0][2], 1)

    def test_output_is_truncated(self):
        long_output = "a" * 30
        fake = FakeTestCommandRunner(TestRunResult(
            command=["test"],
            returncode=0,
            duration_ms=1,
            stdout=long_output,
            stderr="",
        ))
        runner = TestRunner(runner=fake, output_limit=10)

        result = runner.run(["test"])

        self.assertIn("output truncated", result.stdout)
        self.assertIn("Original length: 30 chars.", result.stdout)

    def test_markdown_for_passed_result(self):
        result = TestRunResult(
            command=["python", "-m", "unittest", "discover"],
            returncode=0,
            duration_ms=5,
            stdout="OK\n",
            stderr="",
        )

        markdown = result.to_markdown()

        self.assertIn("Status: passed", markdown)
        self.assertIn("Command: `python -m unittest discover`", markdown)
        self.assertIn("Stdout:", markdown)

    def test_markdown_for_failed_result_with_stderr(self):
        result = TestRunResult(
            command=["pytest"],
            returncode=1,
            duration_ms=5,
            stdout="",
            stderr="failure",
        )

        markdown = result.to_markdown()

        self.assertIn("Status: failed", markdown)
        self.assertIn("Stderr:", markdown)
        self.assertIn("failure", markdown)


if __name__ == "__main__":
    unittest.main()
