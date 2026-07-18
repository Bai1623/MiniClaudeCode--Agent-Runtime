"""Tests for CLI harness options."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from miniclaudecode.cli import (
    build_project_summary,
    build_config,
    build_parser,
    default_harness_tasks,
    list_harness_runs,
    list_memory_records,
    list_tools,
    main,
    run_doctor,
    run_git_commit_message,
    run_git_summary,
    run_harness,
    run_memory_context,
    run_memory_index,
)
from miniclaudecode.config import Config, PermissionMode
from miniclaudecode.git_workflow.diff_summary import DiffSummary, FileChange
from miniclaudecode.git_workflow.test_runner import TestRunResult
from miniclaudecode.git_workflow.workflow import GitWorkflowReport
from miniclaudecode.git_workflow.worktree import WorktreeStatus
from miniclaudecode.harness.artifacts import ArtifactStore
from miniclaudecode.memory import FileFingerprint, FileSummary, MemoryStore, ProjectSummary
from miniclaudecode.tools.base import ToolRegistry


class TestCliHarnessOptions(unittest.TestCase):
    def test_parser_accepts_product_commands(self):
        parser = build_parser()

        self.assertEqual(parser.parse_args(["chat"]).command, "chat")

        run_args = parser.parse_args(["run", "Build", "feature"])
        self.assertEqual(run_args.command, "run")
        self.assertEqual(run_args.prompt, "Build feature")

        tools_args = parser.parse_args(["tools", "list"])
        self.assertEqual(tools_args.command, "tools")
        self.assertEqual(tools_args.command_args, ["list"])

        doctor_args = parser.parse_args(["doctor"])
        self.assertEqual(doctor_args.command, "doctor")

    def test_parser_preserves_legacy_prompt_mode(self):
        args = build_parser().parse_args(["Build feature"])

        self.assertIsNone(args.command)
        self.assertEqual(args.prompt, "Build feature")

    def test_parser_accepts_harness_options(self):
        parser = build_parser()
        args = parser.parse_args([
            "--config",
            "config.json",
            "--run-harness",
            "--harness-task",
            "Task one",
            "--harness-task",
            "Task two",
            "--max-repair-rounds",
            "2",
            "Build feature",
        ])

        self.assertTrue(args.run_harness)
        self.assertEqual(args.config, "config.json")
        self.assertEqual(args.harness_task, ["Task one", "Task two"])
        self.assertEqual(args.max_repair_rounds, 2)
        self.assertEqual(args.prompt, "Build feature")

    def test_build_config_uses_cli_overrides(self):
        parser = build_parser()
        args = parser.parse_args([
            "--model",
            "cli-model",
            "--mode",
            "plan",
            "--max-turns",
            "5",
        ])

        with patch("miniclaudecode.config.os.environ", {}):
            config = build_config(args)

        self.assertEqual(config.model.model, "cli-model")
        self.assertEqual(config.permission_mode, PermissionMode.PLAN)
        self.assertEqual(config.max_turns, 5)

    def test_build_config_loads_harness_runs_dir_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text('{"harness": {"runs_dir": "custom-runs"}}', encoding="utf-8")
            args = build_parser().parse_args(["--config", str(config_path)])

            with patch("miniclaudecode.config.os.environ", {}):
                config = build_config(args)

        self.assertEqual(config.harness.runs_dir, "custom-runs")

    def test_default_harness_tasks_uses_prompt_when_no_task_titles(self):
        tasks = default_harness_tasks("Build feature", None)

        self.assertEqual(tasks[0]["title"], "Build feature")
        self.assertIn("Run or update relevant tests.", tasks[0]["acceptance"])

    def test_default_harness_tasks_uses_explicit_titles(self):
        tasks = default_harness_tasks("Build feature", ["Task one", "Task two"])

        self.assertEqual([task["title"] for task in tasks], ["Task one", "Task two"])

    def test_list_harness_runs_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = StringIO()
            list_harness_runs(ArtifactStore(base_dir=tmpdir), output=output)

        self.assertIn("No harness runs found.", output.getvalue())

    def test_list_harness_runs_outputs_created_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ArtifactStore(base_dir=tmpdir)
            artifacts = store.create_run()
            output = StringIO()
            list_harness_runs(store, output=output)

        self.assertIn("Harness runs:", output.getvalue())
        self.assertIn(artifacts.run_id, output.getvalue())

    def test_list_tools_outputs_registered_tools(self):
        output = StringIO()
        registry = ToolRegistry.default(config=Config(enabled_tools=["read_file"]))

        exit_code = list_tools(registry, output=output)

        self.assertEqual(exit_code, 0)
        self.assertIn("Available tools:", output.getvalue())
        self.assertIn("read_file", output.getvalue())

    def test_run_doctor_outputs_config_and_api_key_status(self):
        output = StringIO()
        registry = ToolRegistry.default(config=Config(enabled_tools=["read_file"]))

        with patch.dict("miniclaudecode.cli.os.environ", {}, clear=True):
            exit_code = run_doctor(Config(model="doctor-model"), registry=registry, output=output)

        self.assertEqual(exit_code, 0)
        self.assertIn("doctor-model", output.getvalue())
        self.assertIn("tools: 1", output.getvalue())
        self.assertIn("anthropic_api_key: missing", output.getvalue())

    def test_main_presents_agent_creation_error(self):
        stderr = StringIO()

        with (
            patch("miniclaudecode.cli.build_agent", side_effect=ValueError("api_key missing")),
            redirect_stderr(stderr),
        ):
            exit_code = main(["run", "hello"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Anthropic API key is missing", stderr.getvalue())
        self.assertIn("How to fix:", stderr.getvalue())

    def test_run_harness_requires_prompt(self):
        args = build_parser().parse_args(["--run-harness"])

        with redirect_stderr(StringIO()):
            self.assertEqual(run_harness(args), 2)

    def test_parser_accepts_git_workflow_options(self):
        parser = build_parser()
        args = parser.parse_args(["--git-summary", "--skip-git-tests"])

        self.assertTrue(args.git_summary)
        self.assertTrue(args.skip_git_tests)

    def test_run_git_summary_prints_markdown_report(self):
        args = build_parser().parse_args(["--git-summary", "--skip-git-tests"])
        output = StringIO()

        with (
            patch("miniclaudecode.cli.build_git_workflow_report", return_value=make_git_report()),
            patch("miniclaudecode.cli.write_git_workflow_memory", return_value=Path("memory.md")),
        ):
            exit_code = run_git_summary(args, output=output)

        self.assertEqual(exit_code, 0)
        self.assertIn("## Git Workflow Report", output.getvalue())
        self.assertIn("Branch: master", output.getvalue())
        self.assertIn("Memory: memory.md", output.getvalue())

    def test_run_git_commit_message_prints_suggested_message(self):
        args = build_parser().parse_args(["--git-commit-message", "--skip-git-tests"])
        output = StringIO()

        with patch("miniclaudecode.cli.build_git_workflow_report", return_value=make_git_report()):
            exit_code = run_git_commit_message(args, output=output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.getvalue().strip(), "Update implementation")

    def test_parser_accepts_memory_options(self):
        args = build_parser().parse_args(["--memory-index"])
        self.assertTrue(args.memory_index)

        args = build_parser().parse_args(["--memory-context", "Fix runtime"])
        self.assertEqual(args.memory_context, "Fix runtime")

        args = build_parser().parse_args(["--list-memory"])
        self.assertTrue(args.list_memory)

    def test_list_memory_records_outputs_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            store.write_project_summary(_project_summary())
            store.write_file_summary(_file_summary("miniclaudecode/cli.py"))
            output = StringIO()

            list_memory_records(store, output=output)

        self.assertIn("Project summary: yes", output.getvalue())
        self.assertIn("File summaries: 1", output.getvalue())

    def test_run_memory_context_prints_and_writes_latest_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            store.write_project_summary(_project_summary())
            store.write_file_summary(
                FileSummary(
                    path="miniclaudecode/memory/context_builder.py",
                    sha256="abc123",
                    size_bytes=10,
                    updated_at="2026-06-29T00:00:00Z",
                    language="python",
                    symbols=["ContextBuilder"],
                    summary="Builds context from memory.",
                )
            )
            args = build_parser().parse_args(["--memory-context", "ContextBuilder"])
            output = StringIO()

            with patch("miniclaudecode.cli.MemoryStore", return_value=store):
                exit_code = run_memory_context(args, output=output)

            saved = store.context_dir / "latest.md"
            saved_exists = saved.exists()

        self.assertEqual(exit_code, 0)
        self.assertTrue(saved_exists)
        self.assertIn("Project Memory Context", output.getvalue())
        self.assertIn("Memory context:", output.getvalue())

    def test_run_memory_index_refreshes_file_summaries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory")
            args = build_parser().parse_args(["--memory-index"])
            output = StringIO()

            with (
                patch("miniclaudecode.cli.MemoryStore", return_value=store),
                patch("miniclaudecode.cli.ProjectIndex", return_value=FakeProjectIndex()),
                patch("miniclaudecode.cli.Summarizer", return_value=FakeSummarizer()),
                patch("miniclaudecode.cli.Path.cwd", return_value=Path("miniClaudeCode-dev")),
            ):
                exit_code = run_memory_index(args, output=output)
            file_summary_count = len(store.list_file_summaries())
            has_project_summary = store.read_project_summary() is not None

        self.assertEqual(exit_code, 0)
        self.assertEqual(file_summary_count, 1)
        self.assertTrue(has_project_summary)
        self.assertIn("Memory index refreshed: 1/1 files", output.getvalue())

    def test_build_project_summary_uses_scanned_files(self):
        summary = build_project_summary(
            [
                FileFingerprint("miniclaudecode/cli.py", "abc", 1, "now"),
                FileFingerprint("tests/test_cli.py", "def", 1, "now"),
            ],
            Path("miniClaudeCode-dev"),
        )

        self.assertEqual(summary.name, "miniClaudeCode-dev")
        self.assertEqual(summary.modules, ["miniclaudecode", "tests"])
        self.assertIn("python -m unittest discover", summary.test_commands)


def make_git_report() -> GitWorkflowReport:
    return GitWorkflowReport(
        status=WorktreeStatus(
            branch="master",
            changed_files=["miniclaudecode/cli.py"],
            untracked_files=[],
            staged_files=[],
            is_dirty=True,
        ),
        diff_summary=DiffSummary(
            files=[FileChange("miniclaudecode/cli.py", "modified", 1, 0)],
            total_additions=1,
            total_deletions=0,
        ),
        test_result=TestRunResult(
            command=["python", "-m", "unittest", "discover"],
            returncode=0,
            duration_ms=1,
            stdout="OK",
            stderr="",
        ),
        commit_message="Update implementation",
    )


class FakeProjectIndex:
    def __init__(self) -> None:
        self.fingerprint = FileFingerprint(
            path="miniclaudecode/cli.py",
            sha256="abc123",
            size_bytes=10,
            updated_at="2026-06-29T00:00:00Z",
        )

    def scan(self):
        return [self.fingerprint]

    def is_summary_stale(self, summary):
        return True


class FakeSummarizer:
    def summarize_file(self, path, fingerprint):
        return FileSummary(
            path=fingerprint.path,
            sha256=fingerprint.sha256,
            size_bytes=fingerprint.size_bytes,
            updated_at=fingerprint.updated_at,
            language="python",
            symbols=["main"],
            summary="CLI entrypoint.",
        )


def _project_summary() -> ProjectSummary:
    return ProjectSummary(
        name="miniClaudeCode",
        updated_at="2026-06-29T00:00:00Z",
        modules=["memory"],
        capabilities=["Memory and Context Engineering"],
        entrypoints=["python -m miniclaudecode"],
        test_commands=["python -m unittest discover"],
    )


def _file_summary(path: str) -> FileSummary:
    return FileSummary(
        path=path,
        sha256="abc123",
        size_bytes=10,
        updated_at="2026-06-29T00:00:00Z",
        language="python",
        symbols=["main"],
        summary="CLI entrypoint.",
    )


if __name__ == "__main__":
    unittest.main()
