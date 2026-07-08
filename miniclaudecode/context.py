"""Context management -- distilled from Claude Code's context system.

Original system includes:
  - Session persistence in ~/.claude/sessions/
  - Context compaction (summarizing old messages when nearing window limit)
  - CLAUDE.md loading for project-level instructions
  - Auto-memory across sessions
  - Transcript stores with flush/replay

Mini version:
  - In-memory message list
  - Deterministic compaction (summarize old messages when over limit)
  - CLAUDE.md loading from project root
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config
from .memory.summarizer import Summarizer

SUMMARY_START = "<conversation_summary>"
SUMMARY_END = "</conversation_summary>"


@dataclass
class Message:
    role: str  # "user", "assistant", "system"
    content: Any  # str or list of content blocks


@dataclass
class ConversationContext:
    """Manages the conversation message history and system prompt."""

    config: Config
    messages: list[dict[str, Any]] = field(default_factory=list)
    _system_prompt: str = ""
    _summarizer: Summarizer = field(default_factory=Summarizer)

    def set_system_prompt(self, prompt: str) -> None:
        self._system_prompt = prompt

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    def add_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})
        self._compact_if_needed()

    def add_assistant_message(self, content: Any) -> None:
        self.messages.append({"role": "assistant", "content": content})
        self._compact_if_needed()

    def add_tool_result(self, tool_use_id: str, content: str, is_error: bool = False) -> None:
        self.messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": content,
                "is_error": is_error,
            }],
        })
        self._compact_if_needed()

    def get_api_messages(self) -> list[dict[str, Any]]:
        return list(self.messages)

    def _compact_if_needed(self) -> None:
        """Compact old messages into a summary block when exceeding the limit."""
        max_msgs = self.config.max_context_messages
        if len(self.messages) <= max_msgs:
            return
        if max_msgs < 3:
            self.messages = self.messages[-max_msgs:]
            return

        keep_first = self.messages[:1]
        recent_budget = max_msgs - 2
        keep_recent = self.messages[-recent_budget:]
        old_messages = self.messages[1:-recent_budget]
        summary = self._summarizer.summarize_conversation(old_messages)
        self.messages = keep_first + [_summary_message(summary)] + keep_recent


def _summary_message(summary: str) -> dict[str, Any]:
    return {
        "role": "user",
        "content": f"{SUMMARY_START}\n{summary}\n{SUMMARY_END}",
    }


def load_project_instructions(project_dir: str | Path | None = None) -> str:
    """Load CLAUDE.md from the project root, similar to how Claude Code does it."""
    if project_dir is None:
        project_dir = Path.cwd()
    else:
        project_dir = Path(project_dir)

    claude_md = project_dir / "CLAUDE.md"
    if claude_md.exists():
        return claude_md.read_text(errors="replace").strip()
    return ""
