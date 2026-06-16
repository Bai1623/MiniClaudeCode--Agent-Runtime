"""Tests for permissions, context management, and system prompt building.

Note: The full AgentLoop requires an Anthropic API key, so we test the
surrounding components that don't need network access.
"""

from __future__ import annotations

import unittest

from miniclaudecode.config import Config, PermissionMode
from miniclaudecode.context import ConversationContext
from miniclaudecode.permissions import PermissionGate
from miniclaudecode.system_prompt import build_system_prompt
from miniclaudecode.tools.base import ToolRegistry, ToolResult
from miniclaudecode.tools.bash_tool import BashTool


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

    def test_error_flag(self):
        r = ToolResult(output="fail", is_error=True)
        self.assertTrue(r.is_error)


if __name__ == "__main__":
    unittest.main()
