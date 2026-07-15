"""End-to-end tests for realistic local coding tasks."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from miniclaudecode.agent_loop import AgentLoop
from miniclaudecode.config import Config, PermissionMode
from miniclaudecode.permissions import PermissionGate
from miniclaudecode.runtime.tool_runtime import ToolRuntime
from miniclaudecode.runtime.tracing import TraceRecorder
from miniclaudecode.tools.base import ToolRegistry

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "e2e_repo"


class FakeStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def __iter__(self):
        return iter(())

    def get_final_message(self):
        return self.response


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self.responses.pop(0))


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def tool_response(tool_id: str, name: str, params: dict):
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                id=tool_id,
                name=name,
                input=params,
            )
        ]
    )


def text_response(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


class TestE2EAgentTask(unittest.TestCase):
    def test_agent_reads_repairs_tests_and_reports_on_fixture_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            shutil.copytree(FIXTURE_REPO, repo)
            trace_dir = repo / ".miniclaudecode" / "traces"
            config = Config(
                permission_mode=PermissionMode.AUTO,
                workspace_root=str(repo),
                max_turns=8,
                max_tool_result_chars=20_000,
            )
            fixed_calculator = "def add(a, b):\n    return a + b\n"
            report = (
                "# E2E Repair Report\n\n"
                "- Read app/calculator.py and tests/test_calculator.py.\n"
                "- Fixed add() to return the sum.\n"
                "- Ran python3 -m unittest discover -s tests successfully.\n"
            )
            responses = [
                tool_response("toolu_read_code", "read_file", {"path": "app/calculator.py"}),
                tool_response("toolu_read_test", "read_file", {"path": "tests/test_calculator.py"}),
                tool_response("toolu_fix", "write_file", {"path": "app/calculator.py", "content": fixed_calculator}),
                tool_response("toolu_test", "bash", {"command": "python3 -m unittest discover -s tests"}),
                tool_response("toolu_report", "write_file", {"path": "REPORT.md", "content": report}),
                text_response("Fixture task repaired and verified."),
            ]
            tracer = TraceRecorder(trace_dir=str(trace_dir))
            output = StringIO()
            agent = AgentLoop(
                config=config,
                registry=ToolRegistry.default(config=config),
                client=FakeClient(responses),
                output=output,
                tracer=tracer,
            )

            result = agent.run_with_result("Fix the calculator bug, run tests, and write a report.")

            self.assertEqual(result.text, "Fixture task repaired and verified.")
            self.assertEqual((repo / "app" / "calculator.py").read_text(encoding="utf-8"), fixed_calculator)
            self.assertIn("Ran python3 -m unittest", (repo / "REPORT.md").read_text(encoding="utf-8"))
            self.assertIn("OK", output.getvalue())
            trace_files = list(trace_dir.glob("*.jsonl"))
            self.assertEqual(len(trace_files), 1)
            events = [
                json.loads(line)
                for line in trace_files[0].read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [event["tool_name"] for event in events],
                ["read_file", "read_file", "write_file", "bash", "write_file"],
            )
            self.assertTrue(all(event["status"] == "ok" for event in events))
            self.assertGreaterEqual(len(agent.client.messages.calls), 6)

    def test_runtime_rejects_dangerous_bash_command_in_fixture_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            shutil.copytree(FIXTURE_REPO, repo)
            config = Config(permission_mode=PermissionMode.AUTO, workspace_root=str(repo))
            registry = ToolRegistry.default(config=config)
            runtime = ToolRuntime(
                registry=registry,
                permission_gate=PermissionGate(config),
                config=config,
                tracer=TraceRecorder(enabled=False),
                output=StringIO(),
            )

            execution = runtime.invoke(
                {"id": "toolu_danger", "name": "bash", "input": {"command": "rm -rf /"}},
                turn=1,
                run_id="e2e",
            )

            self.assertTrue(execution.result.is_error)
            self.assertEqual(execution.result.error_type, "permission_denied")
            self.assertIn("Permission denied", execution.result.output)


if __name__ == "__main__":
    unittest.main()
