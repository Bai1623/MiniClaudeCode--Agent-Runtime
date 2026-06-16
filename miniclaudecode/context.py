"""Context management -- distilled from Claude Code's context system.

Original system includes:
  - Session persistence in ~/.claude/sessions/
  - Context compaction (summarizing old messages when nearing window limit)
  - CLAUDE.md loading for project-level instructions
  - Auto-memory across sessions
  - Transcript stores with flush/replay

Mini version:
  - In-memory message list
  - Simple truncation (drop oldest messages when over limit)
  - CLAUDE.md loading from project root
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config


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

    def set_system_prompt(self, prompt: str) -> None:
        self._system_prompt = prompt

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    def add_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})
        self._truncate_if_needed()

    def add_assistant_message(self, content: Any) -> None:
        self.messages.append({"role": "assistant", "content": content})
        self._truncate_if_needed()

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
        self._truncate_if_needed()

    def get_api_messages(self) -> list[dict[str, Any]]:
        return list(self.messages)

    def _truncate_if_needed(self) -> None:
        """Drop oldest messages when exceeding the limit, keeping the first user message."""
        max_msgs = self.config.max_context_messages
        if len(self.messages) > max_msgs:
            keep_first = self.messages[:1]
            keep_recent = self.messages[-(max_msgs - 1):]
            self.messages = keep_first + keep_recent


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
