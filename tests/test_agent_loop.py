"""Tests for permissions, context management, and system prompt building.

Note: The full AgentLoop requires an Anthropic API key, so we test the
surrounding components that don't need network access.
"""

from __future__ import annotations

import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace

if "anthropic" not in sys.modules:
    sys.modules["anthropic"] = SimpleNamespace(Anthropic=lambda: None)

from miniclaudecode.agent_loop import AgentLoop
from miniclaudecode.config import Config, PermissionMode
from miniclaudecode.context import ConversationContext
from miniclaudecode.permissions import PermissionGate
from miniclaudecode.runtime.tool_runtime import ToolExecution
from miniclaudecode.runtime.tracing import TraceRecorder
from miniclaudecode.system_prompt import build_system_prompt
from miniclaudecode.tools.base import Tool, ToolRegistry, ToolResult
from miniclaudecode.tools.bash_tool import BashTool


class FakeStream:
    def __init__(self, response, events=None):
        self.response = response
        self.events = events or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def __iter__(self):
        return iter(self.events)

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


class StaticTool(Tool):
    @property
    def name(self) -> str:
        return "static"

    @property
    def description(self) -> str:
        return "Return static output."

    @property
    def input_schema(self):
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, params):
        return ToolResult(output="tool output")


class TestPermissionGate(unittest.TestCase):
    def test_auto_mode_allows_all(self):
        config = Config(permission_mode=PermissionMode.AUTO)
        gate = PermissionGate(config)
        tool = BashTool()
        result = gate.check(tool, {"command": "echo hello"})
        self.assertIsNone(result)

    def test_plan_mode_blocks_writes(self):
        config = Config(permission_mode=PermissionMode.PLAN)
        gate = PermissionGate(config)
        tool = BashTool()
        result = gate.check(tool, {"command": "echo hello"})
        self.assertIsNotNone(result)
        self.assertTrue(result.is_error)

    def test_tool_level_denial_takes_priority(self):
        config = Config(permission_mode=PermissionMode.AUTO)
        gate = PermissionGate(config)
        tool = BashTool()
        result = gate.check(tool, {"command": "rm -rf /"})
        self.assertIsNotNone(result)
        self.assertTrue(result.is_error)


class TestConversationContext(unittest.TestCase):
    def test_add_messages(self):
        config = Config(max_context_messages=10)
        ctx = ConversationContext(config=config)
        ctx.add_user_message("hello")
        ctx.add_assistant_message("hi")
        msgs = ctx.get_api_messages()
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[1]["role"], "assistant")

    def test_truncation(self):
        config = Config(max_context_messages=5)
        ctx = ConversationContext(config=config)
        for i in range(10):
            ctx.add_user_message(f"msg {i}")
        msgs = ctx.get_api_messages()
        self.assertLessEqual(len(msgs), 5)
        # First message should be preserved
        self.assertEqual(msgs[0]["content"], "msg 0")

    def test_system_prompt(self):
        ctx = ConversationContext(config=Config())
        ctx.set_system_prompt("You are helpful.")
        self.assertEqual(ctx.system_prompt, "You are helpful.")


class TestSystemPrompt(unittest.TestCase):
    def test_build_includes_tools(self):
        registry = ToolRegistry.default()
        prompt = build_system_prompt(registry, permission_mode="ask")
        self.assertIn("bash", prompt)
        self.assertIn("read_file", prompt)
        self.assertIn("ASK", prompt)

    def test_plan_mode_description(self):
        registry = ToolRegistry.default()
        prompt = build_system_prompt(registry, permission_mode="plan")
        self.assertIn("read-only", prompt)


class TestToolResultDataclass(unittest.TestCase):
    def test_default_not_error(self):
        r = ToolResult(output="ok")
        self.assertFalse(r.is_error)
        self.assertIsNone(r.error_type)
        self.assertEqual(r.metadata, {})

    def test_error_flag(self):
        r = ToolResult(output="fail", is_error=True, error_type="execution_error", metadata={"tool": "bash"})
        self.assertTrue(r.is_error)
        self.assertEqual(r.error_type, "execution_error")
        self.assertEqual(r.metadata["tool"], "bash")


class TestAgentLoopRuntimeIntegration(unittest.TestCase):
    def test_execute_tool_calls_delegates_to_runtime(self):
        agent = SimpleNamespace()
        agent.context = ConversationContext(config=Config())
        agent.output = StringIO()

        calls = []

        class FakeRuntime:
            def invoke(self, call, turn, run_id):
                calls.append((call, turn, run_id))
                return ToolExecution(
                    tool_use_id=call["id"],
                    result=ToolResult(output="runtime ok"),
                )

        agent.tool_runtime = FakeRuntime()
        with redirect_stdout(StringIO()):
            AgentLoop._execute_tool_calls(
                agent,
                [{"id": "toolu_1", "name": "fake", "input": {"x": 1}}],
                turn=3,
                run_id="run_1",
            )

        self.assertEqual(calls[0][1], 3)
        self.assertEqual(calls[0][2], "run_1")
        self.assertEqual(agent.context.messages[0]["role"], "user")
        self.assertEqual(agent.context.messages[0]["content"][0], {
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "content": "runtime ok",
            "is_error": False,
        })

    def test_run_with_result_uses_injected_client_and_output(self):
        response = SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="final answer"),
            ]
        )
        output = StringIO()
        agent = AgentLoop(
            config=Config(permission_mode=PermissionMode.AUTO),
            client=FakeClient([response]),
            output=output,
            tracer=TraceRecorder(enabled=False),
        )

        result = agent.run_with_result("hello")

        self.assertEqual(result.text, "final answer")
        self.assertEqual(result.turns, 1)
        self.assertFalse(result.reached_max_turns)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(agent.client.messages.calls[0]["model"], agent.config.model.model)

    def test_run_executes_tool_call_then_finishes(self):
        registry = ToolRegistry()
        registry.register(StaticTool())
        first_response = SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    id="toolu_1",
                    name="static",
                    input={},
                )
            ]
        )
        second_response = SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="done"),
            ]
        )
        output = StringIO()
        agent = AgentLoop(
            config=Config(permission_mode=PermissionMode.AUTO),
            registry=registry,
            client=FakeClient([first_response, second_response]),
            output=output,
            tracer=TraceRecorder(enabled=False),
        )

        result = agent.run_with_result("call tool")

        self.assertEqual(result.text, "done")
        self.assertEqual(result.turns, 2)
        self.assertIn("[Tool: static]", output.getvalue())
        self.assertIn("[OK] tool output", output.getvalue())
        self.assertEqual(agent.context.messages[-2]["content"][0]["content"], "tool output")

    def test_run_result_marks_max_turns(self):
        response = SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    id="toolu_1",
                    name="missing",
                    input={},
                )
            ]
        )
        agent = AgentLoop(
            config=Config(max_turns=1, permission_mode=PermissionMode.AUTO),
            client=FakeClient([response]),
            output=StringIO(),
            tracer=TraceRecorder(enabled=False),
        )

        result = agent.run_with_result("loop")

        self.assertTrue(result.reached_max_turns)
        self.assertEqual(result.turns, 1)


if __name__ == "__main__":
    unittest.main()
