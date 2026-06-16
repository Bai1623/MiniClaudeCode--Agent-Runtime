"""CLI entry point -- distilled from Claude Code's 20+ subcommand CLI.

Original: argparse with subcommands for summary, manifest, parity-audit, bootstrap,
turn-loop, remote-mode, ssh-mode, etc., plus an Ink/React terminal UI.

Mini version: simple interactive REPL with 3 commands: chat (default), tools, help.
"""

from __future__ import annotations

import argparse
import sys

from .config import Config, PermissionMode
from .harness.artifacts import ArtifactStore
from .harness.evaluator import Evaluator
from .harness.executor import Executor
from .harness.planner import Planner
from .harness.report import FinalReportGenerator
from .harness.task_harness import TaskHarness
from .tools.base import ToolRegistry


BANNER = r"""
  ╔══════════════════════════════════════╗
  ║       miniClaudeCode v0.1.0         ║
  ║  Distilled Agent Loop Framework     ║
  ╚══════════════════════════════════════╝

  Type your message to start. Commands:
    /tools   -- list available tools
    /mode    -- show/change permission mode
    /help    -- show help
    /quit    -- exit
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="miniClaudeCode -- a distilled Claude Code agent loop",
    )
    parser.add_argument(
        "--model", default="claude-sonnet-4-20250514",
        help="Anthropic model to use (default: claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "--mode", choices=["ask", "auto", "plan"], default="ask",
        help="Permission mode (default: ask)",
    )
    parser.add_argument(
        "--max-turns", type=int, default=30,
        help="Max agent loop turns per message (default: 30)",
    )
    parser.add_argument(
        "--list-runs",
        action="store_true",
        help="List saved harness runs and exit.",
    )
    parser.add_argument(
        "--run-harness",
        action="store_true",
        help="Run the prompt through the Planner Executor Evaluator harness.",
    )
    parser.add_argument(
        "--harness-task",
        action="append",
        default=None,
        help="Task title for harness mode. Can be provided multiple times.",
    )
    parser.add_argument(
        "--harness-spec",
        default="",
        help="Optional spec text to write into the harness run.",
    )
    parser.add_argument(
        "--max-repair-rounds",
        type=int,
        default=1,
        help="Max evaluator repair rounds in harness mode (default: 1).",
    )
    parser.add_argument(
        "prompt", nargs="?", default=None,
        help="Optional one-shot prompt (non-interactive mode)",
    )
    return parser


def run_interactive(agent: "AgentLoop") -> None:
    """Interactive REPL loop."""
    print(BANNER)

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd = user_input.lower().split()[0]
            if cmd in ("/quit", "/exit", "/q"):
                print("Goodbye!")
                break
            elif cmd == "/tools":
                print("\nAvailable tools:")
                for tool in agent.registry.all_tools():
                    print(f"  - {tool.name}: {tool.description}")
                continue
            elif cmd == "/mode":
                parts = user_input.split()
                if len(parts) > 1 and parts[1] in ("ask", "auto", "plan"):
                    agent.config.permission_mode = PermissionMode(parts[1])
                    print(f"Mode changed to: {parts[1]}")
                else:
                    print(f"Current mode: {agent.config.permission_mode.value}")
                    print("Usage: /mode [ask|auto|plan]")
                continue
            elif cmd == "/help":
                print(BANNER)
                continue
            else:
                print(f"Unknown command: {cmd}. Type /help for help.")
                continue

        print()
        try:
            agent.run(user_input)
        except KeyboardInterrupt:
            print("\n(interrupted)")
        except Exception as exc:
            print(f"\nError: {exc}", file=sys.stderr)


def build_config(args: argparse.Namespace) -> Config:
    return Config(
        model=args.model,
        permission_mode=PermissionMode(args.mode),
        max_turns=args.max_turns,
    )


def build_agent(args: argparse.Namespace) -> "AgentLoop":
    from .agent_loop import AgentLoop

    return AgentLoop(
        config=build_config(args),
        registry=ToolRegistry.default(),
    )


def list_harness_runs(store: ArtifactStore, output=sys.stdout) -> None:
    runs = store.list_runs()
    if not runs:
        print("No harness runs found.", file=output)
        return

    print("Harness runs:", file=output)
    for run in runs:
        print(f"  {run.run_id}  {run.root}", file=output)


def default_harness_tasks(prompt: str, task_titles: list[str] | None) -> list[dict]:
    titles = task_titles or [prompt]
    return [
        {
            "title": title,
            "acceptance": [
                "Implement the requested change.",
                "Run or update relevant tests.",
            ],
        }
        for title in titles
    ]


def run_harness(args: argparse.Namespace) -> int:
    if not args.prompt:
        print("Error: --run-harness requires a prompt.", file=sys.stderr)
        return 2

    store = ArtifactStore()
    agent = build_agent(args)
    harness = TaskHarness(
        store=store,
        planner=Planner(),
        executor=Executor(agent),
        evaluator=Evaluator(),
        max_repair_rounds=args.max_repair_rounds,
    )
    result = harness.run(
        request=args.prompt,
        goal=args.prompt,
        spec=args.harness_spec,
        tasks=default_harness_tasks(args.prompt, args.harness_task),
    )
    FinalReportGenerator().write(store, result)

    print(f"Harness run: {result.artifacts.run_id}")
    print(f"Status: {result.status}")
    print(f"Artifacts: {result.artifacts.root}")
    print(f"Final report: {result.artifacts.final_report_path}")
    return 0 if result.status == "passed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_runs:
        list_harness_runs(ArtifactStore())
        return 0

    if args.run_harness:
        return run_harness(args)

    agent = build_agent(args)

    if args.prompt:
        try:
            agent.run(args.prompt)
            print()
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    run_interactive(agent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
