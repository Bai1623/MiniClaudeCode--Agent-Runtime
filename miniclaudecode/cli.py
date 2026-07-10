"""CLI entry point -- distilled from Claude Code's 20+ subcommand CLI.

Original: argparse with subcommands for summary, manifest, parity-audit, bootstrap,
turn-loop, remote-mode, ssh-mode, etc., plus an Ink/React terminal UI.

Mini version: product-oriented commands for chat, one-shot runs, tools, and doctor.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, TypeVar, overload

from .config import Config, PermissionMode, load_config
from .harness.artifacts import ArtifactStore
from .harness.evaluator import Evaluator
from .harness.executor import Executor
from .harness.planner import Planner, TaskSpec
from .harness.report import FinalReportGenerator
from .harness.task_harness import TaskHarness
from .tools.base import ToolRegistry

if TYPE_CHECKING:
    from .agent_loop import AgentLoop


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

PRODUCT_COMMANDS = {"chat", "run", "tools", "doctor"}
_N = TypeVar("_N")


class MiniArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that keeps legacy prompt mode while adding commands."""

    @overload
    def parse_args(
        self,
        args: Sequence[str] | None = ...,
        namespace: None = ...,
    ) -> argparse.Namespace:
        ...

    @overload
    def parse_args(
        self,
        args: Sequence[str] | None,
        namespace: _N,
    ) -> _N:
        ...

    @overload
    def parse_args(
        self,
        *,
        namespace: _N,
    ) -> _N:
        ...

    def parse_args(
        self,
        args: Sequence[str] | None = None,
        namespace: Any = None,
    ) -> Any:
        parsed = super().parse_args(args, namespace)
        return normalize_cli_args(parsed)


def build_parser() -> argparse.ArgumentParser:
    parser = MiniArgumentParser(
        description="miniClaudeCode -- a distilled Claude Code agent loop",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to a JSON config file. CLI flags override file and environment values.",
    )
    parser.add_argument(
        "--model", default=None,
        help="Anthropic model to use.",
    )
    parser.add_argument(
        "--mode", choices=["ask", "auto", "plan"], default=None,
        help="Permission mode.",
    )
    parser.add_argument(
        "--max-turns", type=int, default=None,
        help="Max agent loop turns per message.",
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
        "--git-summary",
        action="store_true",
        help="Analyze the current git workflow state and print a Markdown report.",
    )
    parser.add_argument(
        "--git-commit-message",
        action="store_true",
        help="Analyze the current git workflow state and print a suggested commit message.",
    )
    parser.add_argument(
        "--skip-git-tests",
        action="store_true",
        help="Skip tests when generating git workflow summaries.",
    )
    parser.add_argument(
        "--harness-task",
        action="append",
        default=None,
        help="Task title for harness mode. Can be provided multiple times.",
    )
    parser.add_argument(
        "--harness-spec",
        default=None,
        help="Optional spec text to write into the harness run.",
    )
    parser.add_argument(
        "--max-repair-rounds",
        type=int,
        default=None,
        help="Max evaluator repair rounds in harness mode.",
    )
    parser.add_argument(
        "command_or_prompt",
        nargs="?",
        default=None,
        help="Command (chat, run, tools, doctor) or legacy one-shot prompt.",
    )
    parser.add_argument(
        "prompt_args",
        nargs=argparse.REMAINDER,
        help="Additional command arguments or prompt words.",
    )
    return parser


def normalize_cli_args(args: argparse.Namespace) -> argparse.Namespace:
    """Normalize product commands while preserving legacy prompt behavior."""
    command_or_prompt = args.command_or_prompt
    rest = list(args.prompt_args or [])
    if command_or_prompt in PRODUCT_COMMANDS:
        args.command = command_or_prompt
        args.command_args = rest
        args.prompt = (" ".join(rest).strip() or None) if command_or_prompt == "run" else None
    else:
        prompt_parts = [part for part in [command_or_prompt, *rest] if part]
        args.command = None
        args.command_args = []
        args.prompt = " ".join(prompt_parts).strip() or None
    return args


def run_interactive(agent: AgentLoop) -> None:
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
    return load_config(
        args.config,
        cli_overrides={
            "model.model": args.model,
            "safety.permission_mode": args.mode,
            "model.max_turns": args.max_turns,
            "harness.max_repair_rounds": args.max_repair_rounds,
        },
    )


def build_agent(args: argparse.Namespace, config: Config | None = None) -> AgentLoop:
    from .agent_loop import AgentLoop

    config = config or build_config(args)
    return AgentLoop(
        config=config,
        registry=ToolRegistry.default(config=config),
    )


def list_harness_runs(store: ArtifactStore, output=sys.stdout) -> None:
    runs = store.list_runs()
    if not runs:
        print("No harness runs found.", file=output)
        return

    print("Harness runs:", file=output)
    for run in runs:
        print(f"  {run.run_id}  {run.root}", file=output)


def list_tools(registry: ToolRegistry, output=sys.stdout) -> int:
    tools = registry.all_tools()
    if not tools:
        print("No tools registered.", file=output)
        return 0

    print("Available tools:", file=output)
    for tool in tools:
        print(f"  - {tool.name}: {tool.description}", file=output)
    return 0


def run_doctor(config: Config, registry: ToolRegistry | None = None, output=sys.stdout) -> int:
    registry = registry or ToolRegistry.default(config=config)
    workspace_root = config.workspace_root
    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

    print("miniClaudeCode doctor", file=output)
    print(f"  model: {config.model.model}", file=output)
    print(f"  permission_mode: {config.permission_mode.value}", file=output)
    print(f"  max_turns: {config.max_turns}", file=output)
    print(f"  workspace_root: {workspace_root}", file=output)
    print(f"  harness_runs_dir: {config.harness.runs_dir}", file=output)
    print(f"  tools: {len(registry.all_tools())}", file=output)
    print(f"  anthropic_api_key: {'set' if has_api_key else 'missing'}", file=output)
    if not has_api_key:
        print("  warning: set ANTHROPIC_API_KEY before running chat or run.", file=output)
    return 0


def default_harness_tasks(prompt: str, task_titles: list[str] | None) -> list[TaskSpec | dict[str, Any]]:
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


def run_harness(args: argparse.Namespace, config: Config | None = None) -> int:
    if not args.prompt:
        print("Error: --run-harness requires a prompt.", file=sys.stderr)
        return 2

    config = config or build_config(args)
    store = ArtifactStore(base_dir=config.harness.runs_dir)
    agent = build_agent(args, config=config)
    harness = TaskHarness(
        store=store,
        planner=Planner(),
        executor=Executor(agent),
        evaluator=Evaluator(),
        max_repair_rounds=config.harness.max_repair_rounds,
    )
    result = harness.run(
        request=args.prompt,
        goal=args.prompt,
        spec=args.harness_spec or "",
        tasks=default_harness_tasks(args.prompt, args.harness_task),
    )
    git_report = build_git_workflow_report(args)
    FinalReportGenerator().write(store, result, git_report=git_report)

    print(f"Harness run: {result.artifacts.run_id}")
    print(f"Status: {result.status}")
    print(f"Artifacts: {result.artifacts.root}")
    print(f"Final report: {result.artifacts.final_report_path}")
    return 0 if result.status == "passed" else 1


def build_git_workflow_report(args: argparse.Namespace):
    from .git_workflow import GitWorkflow

    return GitWorkflow().analyze(run_tests=not args.skip_git_tests)


def run_git_summary(args: argparse.Namespace, output=sys.stdout) -> int:
    try:
        report = build_git_workflow_report(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(report.to_markdown(), file=output)
    return 0


def run_git_commit_message(args: argparse.Namespace, output=sys.stdout) -> int:
    try:
        report = build_git_workflow_report(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(report.commit_message, file=output)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = build_config(args)

    if args.list_runs:
        list_harness_runs(ArtifactStore(base_dir=config.harness.runs_dir))
        return 0

    if args.run_harness:
        return run_harness(args, config=config)

    if args.git_summary:
        return run_git_summary(args)

    if args.git_commit_message:
        return run_git_commit_message(args)

    if args.command == "tools":
        return list_tools(ToolRegistry.default(config=config))

    if args.command == "doctor":
        return run_doctor(config)

    agent = build_agent(args, config=config)

    if args.command == "run":
        if not args.prompt:
            print("Error: run requires a prompt.", file=sys.stderr)
            return 2
        try:
            agent.run(args.prompt)
            print()
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.prompt:
        try:
            agent.run(args.prompt)
            print()
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "chat":
        run_interactive(agent)
        return 0

    run_interactive(agent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
