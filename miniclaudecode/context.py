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

import json
import math
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
        if _content_contains_tool_use(content):
            return
        self._compact_if_needed()

    def add_tool_result(self, tool_use_id: str, content: str, is_error: bool = False) -> None:
        self.add_tool_results([{
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content,
            "is_error": is_error,
        }])

    def add_tool_results(self, results: list[dict[str, Any]]) -> None:
        """Add all results for an assistant tool-use turn as one atomic message."""
        self.messages.append({
            "role": "user",
            "content": results,
        })
        self._compact_if_needed()

    def get_api_messages(self) -> list[dict[str, Any]]:
        return list(self.messages)

    def estimated_tokens(self) -> int:
        """Estimate request tokens without a provider-specific tokenizer dependency."""
        return _estimate_tokens(self._system_prompt) + sum(
            _estimate_tokens(message) for message in self.messages
        )

    def _compact_if_needed(self) -> None:
        """Compact complete conversation groups when either context budget is exceeded."""
        max_msgs = self.config.max_context_messages
        max_tokens = self.config.max_context_tokens
        if len(self.messages) <= max_msgs and self.estimated_tokens() <= max_tokens:
            return

        groups = _message_groups(self.messages)
        if len(groups) <= 1:
            return

        first_group = groups[0]
        retained_groups: list[list[dict[str, Any]]] = []
        old_groups = groups[1:]
        while old_groups:
            candidate = old_groups[-1]
            candidate_messages = first_group + [_summary_message("Pending summary.")] + candidate
            candidate_messages.extend(
                message for group in retained_groups for message in group
            )
            if (
                len(candidate_messages) > max_msgs
                or _estimate_context_tokens(self._system_prompt, candidate_messages) > max_tokens
            ):
                break
            retained_groups.insert(0, old_groups.pop())

        old_messages = [message for group in old_groups for message in group]
        if not old_messages:
            return
        compacted = _compacted_messages(
            self._system_prompt,
            first_group,
            retained_groups,
            old_messages,
            self._summarizer,
            max_tokens,
        )
        while retained_groups and (
            len(compacted) > max_msgs
            or _estimate_context_tokens(self._system_prompt, compacted) > max_tokens
        ):
            old_group = retained_groups.pop(0)
            old_messages.extend(old_group)
            compacted = _compacted_messages(
                self._system_prompt,
                first_group,
                retained_groups,
                old_messages,
                self._summarizer,
                max_tokens,
            )

        if len(compacted) <= max_msgs and _estimate_context_tokens(self._system_prompt, compacted) <= max_tokens:
            self.messages = compacted
            return

        # A very small budget cannot hold the first turn and a summary. Keep the latest
        # complete group rather than splitting a tool_use/tool_result protocol pair.
        self.messages = groups[-1]


def _summary_message(summary: str) -> dict[str, Any]:
    return {
        "role": "user",
        "content": f"{SUMMARY_START}\n{summary}\n{SUMMARY_END}",
    }


def _compacted_messages(
    system_prompt: str,
    first_group: list[dict[str, Any]],
    retained_groups: list[list[dict[str, Any]]],
    old_messages: list[dict[str, Any]],
    summarizer: Summarizer,
    max_tokens: int,
) -> list[dict[str, Any]]:
    retained_messages = [message for group in retained_groups for message in group]
    summary = summarizer.summarize_conversation(old_messages)
    summary_message = _budgeted_summary_message(
        system_prompt,
        first_group + retained_messages,
        summary,
        max_tokens,
    )
    return first_group + [summary_message] + retained_messages


def _budgeted_summary_message(
    system_prompt: str,
    retained_messages: list[dict[str, Any]],
    summary: str,
    max_tokens: int,
) -> dict[str, Any]:
    """Truncate a generated summary until it fits the remaining token budget."""
    low, high = 0, len(summary)
    best = ""
    while low <= high:
        middle = (low + high) // 2
        candidate = summary[:middle].rstrip()
        if middle < len(summary):
            candidate += "..."
        message = _summary_message(candidate)
        if _estimate_context_tokens(system_prompt, retained_messages + [message]) <= max_tokens:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return _summary_message(best)


def _message_groups(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group tool_use messages with their following tool_result message."""
    groups: list[list[dict[str, Any]]] = []
    index = 0
    while index < len(messages):
        current = messages[index]
        if (
            _contains_tool_use(current)
            and index + 1 < len(messages)
            and _contains_tool_result(messages[index + 1])
        ):
            groups.append([current, messages[index + 1]])
            index += 2
            continue
        groups.append([current])
        index += 1
    return groups


def _contains_tool_use(message: dict[str, Any]) -> bool:
    return _content_contains_tool_use(message.get("content"))


def _contains_tool_result(message: dict[str, Any]) -> bool:
    content = message.get("content")
    return isinstance(content, list) and any(
        _block_type(block) == "tool_result" for block in content
    )


def _content_contains_tool_use(content: Any) -> bool:
    return isinstance(content, list) and any(
        _block_type(block) == "tool_use" for block in content
    )


def _block_type(block: Any) -> Any:
    return block.get("type") if isinstance(block, dict) else getattr(block, "type", None)


def _estimate_context_tokens(system_prompt: str, messages: list[dict[str, Any]]) -> int:
    return _estimate_tokens(system_prompt) + sum(_estimate_tokens(message) for message in messages)


def _estimate_tokens(value: Any) -> int:
    """Conservative deterministic token estimate for mixed-language API payloads."""
    if not isinstance(value, str):
        value = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        )
    cjk_chars = sum(1 for char in value if "\u4e00" <= char <= "\u9fff")
    other_chars = len(value) - cjk_chars
    return max(1, cjk_chars + math.ceil(other_chars / 4)) if value else 0


def _json_default(value: Any) -> Any:
    if hasattr(value, "__dict__"):
        return vars(value)
    return str(value)


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
