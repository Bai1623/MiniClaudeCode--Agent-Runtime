"""System prompt builder -- distilled from Claude Code's system_init + prompt assembly.

Original: merges system prompt from defaults, CLAUDE.md, memory files, tool definitions,
permission mode instructions, and hook-injected context.

Mini version: single template with tool list and optional CLAUDE.md.
"""

from __future__ import annotations

from .context import load_project_instructions
from .tools.base import ToolRegistry

SYSTEM_PROMPT_TEMPLATE = """\
You are miniClaudeCode, a lightweight AI coding assistant that operates in the terminal.

You have access to the following tools to help the user with software engineering tasks:
{tool_list}

## Operating Rules

1. Always read a file before editing it.
2. Use tools to accomplish tasks -- don't just describe what to do.
3. When running bash commands, prefer non-destructive read operations.
4. For file edits, provide enough context in old_string to uniquely match.
5. Be concise and direct in your responses.

## Current Permission Mode: {permission_mode}
{mode_description}

{project_instructions}"""

MODE_DESCRIPTIONS = {
    "ask": "In ASK mode, potentially dangerous operations will require user confirmation.",
    "auto": "In AUTO mode, all operations are auto-approved (use with caution).",
    "plan": "In PLAN mode, only read-only operations are allowed. Write operations are blocked.",
}


def build_system_prompt(
    registry: ToolRegistry,
    permission_mode: str = "ask",
    project_dir: str | None = None,
) -> str:
    tool_list = "\n".join(
        f"- **{t.name}**: {t.description}"
        for t in registry.all_tools()
    )

    instructions = load_project_instructions(project_dir)
    project_section = ""
    if instructions:
        project_section = f"## Project Instructions (from CLAUDE.md)\n\n{instructions}"

    return SYSTEM_PROMPT_TEMPLATE.format(
        tool_list=tool_list,
        permission_mode=permission_mode.upper(),
        mode_description=MODE_DESCRIPTIONS.get(permission_mode, ""),
        project_instructions=project_section,
    ).strip()
