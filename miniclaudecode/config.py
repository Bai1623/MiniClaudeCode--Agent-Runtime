from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PermissionMode(Enum):
    ASK = "ask"
    AUTO = "auto"
    PLAN = "plan"


@dataclass
class Config:
    model: str = "claude-sonnet-4-20250514"
    max_turns: int = 30
    max_context_messages: int = 100
    max_output_chars: int = 50_000
    permission_mode: PermissionMode = PermissionMode.ASK
    allowed_commands: list[str] = field(default_factory=lambda: [
        "ls", "cat", "head", "tail", "wc", "find", "grep", "rg",
        "git status", "git diff", "git log", "git branch",
        "python", "python3", "pip", "npm", "node",
        "echo", "pwd", "which", "env", "date",
    ])
    denied_patterns: list[str] = field(default_factory=lambda: [
        "rm -rf /", "rm -rf ~", "sudo rm",
        "git push --force", "git reset --hard",
        "> /dev/sda", "mkfs", "dd if=",
    ])
