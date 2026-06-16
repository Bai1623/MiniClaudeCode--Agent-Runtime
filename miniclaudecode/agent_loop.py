"""Agent Loop -- the heart of miniClaudeCode.

Distilled from Claude Code's agentic loop architecture:

Original flow (streaming-first, SSE):
  1. Receive prompt + tool definitions
  2. Call Claude API (streaming SSE)
  3. Parse response for tool_use blocks (can be multiple parallel calls)
  4. Run permission gauntlet (5 layers)
  5. Execute tools, append results to conversation
  6. Repeat until Claude responds with no tool calls (end_turn)

Mini flow (synchronous, simplified):
  1. Receive prompt
  2. Call Claude API (streaming)
  3. Parse response for tool_use blocks (single sequential execution)
  4. Invoke ToolRuntime for validation, permissions, preview, execution, and tracing
  5. Append tool results
  6. Repeat until no tool calls or max_turns reached
"""

from __future__ import annotations

import sys
from typing import Any

import anthropic

from .config import Config
from .context import ConversationContext
from .permissions import PermissionGate
from .runtime.tool_runtime import ToolRuntime
from .runtime.tracing import TraceRecorder
from .system_prompt import build_system_prompt
from .tools.base import ToolRegistry


class AgentLoop:
    """The core agent loop that drives miniClaudeCode.

    Mirrors Claude Code's loop: prompt -> LLM -> tool_use? -> execute -> loop
    until the LLM produces a final text-only response.
    """

    def __init__(
        self,
        config: Config | None = None,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.config = config or Config()
        self.registry = registry or ToolRegistry.default()
        self.permission_gate = PermissionGate(self.config)
        self.context = ConversationContext(config=self.config)
        self.client = anthropic.Anthropic()
        self.tracer = TraceRecorder()
        self.tool_runtime = ToolRuntime(
            registry=self.registry,
            permission_gate=self.permission_gate,
            config=self.config,
            tracer=self.tracer,
            output=sys.stdout,
        )

        system_prompt = build_system_prompt(
            self.registry,
            permission_mode=self.config.permission_mode.value,
        )
        self.context.set_system_prompt(system_prompt)

    def run(self, user_message: str) -> str:
        """Process a user message through the agent loop, returning the final text response."""
        self.context.add_user_message(user_message)
        run_id = self.tracer.start_run()
        final_text = ""

        for turn in range(1, self.config.max_turns + 1):
            response = self._call_api()
            tool_calls, text_parts = self._parse_response(response)

            if text_parts:
                final_text = "\n".join(text_parts)

            if not tool_calls:
                # No tool calls -- the loop ends, return the text
                self.context.add_assistant_message(response.content)
                break

            # There are tool calls -- execute them and continue the loop
            self.context.add_assistant_message(response.content)
            self._execute_tool_calls(tool_calls, turn=turn, run_id=run_id)
        else:
            if not final_text:
                final_text = "(max turns reached without a final response)"

        return final_text

    def _call_api(self) -> Any:
        """Call the Anthropic API with streaming output enabled."""
        with self.client.messages.stream(
            model=self.config.model,
            max_tokens=8192,
            system=self.context.system_prompt,
            tools=self.registry.api_schemas(),
            messages=self.context.get_api_messages(),
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    sys.stdout.write(event.delta.text)
                    sys.stdout.flush()
            return stream.get_final_message()

    def _parse_response(self, response: Any) -> tuple[list[dict], list[str]]:
        """Extract tool_use blocks and text blocks from the API response."""
        tool_calls: list[dict] = []
        text_parts: list[str] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
                sys.stdout.write(f"\n[Tool: {block.name}] ")
                _input_preview = str(block.input)
                if len(_input_preview) > 120:
                    _input_preview = _input_preview[:120] + "..."
                sys.stdout.write(f"{_input_preview}\n")
                sys.stdout.flush()

        return tool_calls, text_parts

    def _execute_tool_calls(self, tool_calls: list[dict], turn: int, run_id: str) -> None:
        """Execute each tool call through ToolRuntime, append results."""
        tool_results = []
        for call in tool_calls:
            execution = self.tool_runtime.invoke(call, turn=turn, run_id=run_id)
            result = execution.result
            output_preview = result.output
            if len(output_preview) > 300:
                output_preview = output_preview[:300] + "..."
            status = "ERROR" if result.is_error else "OK"
            sys.stdout.write(f"  -> [{status}] {output_preview}\n")
            sys.stdout.flush()
            tool_results.append(execution.to_api_result())

        # Append all tool results as a single user message (Anthropic API format)
        self.context.messages.append({
            "role": "user",
            "content": tool_results,
        })
