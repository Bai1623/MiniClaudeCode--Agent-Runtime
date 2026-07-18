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
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, overload

from .config import Config, PermissionMode, load_config
from .errors import ErrorPresenter
from .harness.artifacts import ArtifactStore
from .harness.evaluator import Evaluator
from .harness.executor import Executor
from .harness.planner import Planner, TaskSpec
from .harness.report import FinalReportGenerator
from .harness.task_harness import TaskHarness
from .memory import ContextBuilder, MemoryStore, ProjectIndex, ProjectSummary, Summarizer
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
ERROR_PRESENTER = ErrorPresenter()


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
        "--memory-index",
        action="store_true",
        help="Refresh project memory summaries and exit.",
    )
    parser.add_argument(
        "--memory-context",
        metavar="TASK",
        help="Build task-specific memory context, write it to memory, and print it.",
    )
    parser.add_argument(
        "--list-memory",
        action="store_true",
        help="List saved memory records and exit.",
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
            print(file=sys.stderr)
            ERROR_PRESENTER.print(exc, output=sys.stderr)


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
        memory_store=MemoryStore(),
    )
    try:
        result = harness.run(
            request=args.prompt,
            goal=args.prompt,
            spec=args.harness_spec or "",
            tasks=default_harness_tasks(args.prompt, args.harness_task),
        )
        git_report = build_git_workflow_report(args)
        FinalReportGenerator().write(store, result, git_report=git_report)
    except Exception as exc:
        ERROR_PRESENTER.print(exc, output=sys.stderr)
        return 1

    print(f"Harness run: {result.artifacts.run_id}")
    print(f"Status: {result.status}")
    print(f"Artifacts: {result.artifacts.root}")
    print(f"Final report: {result.artifacts.final_report_path}")
    if result.memory_path is not None:
        print(f"Memory: {result.memory_path}")
    return 0 if result.status == "passed" else 1


def build_git_workflow_report(args: argparse.Namespace):
    from .git_workflow import GitWorkflow

    return GitWorkflow().analyze(run_tests=not args.skip_git_tests)


def run_git_summary(args: argparse.Namespace, output=sys.stdout) -> int:
    try:
        report = build_git_workflow_report(args)
    except Exception as exc:
        ERROR_PRESENTER.print(exc, output=sys.stderr)
        return 1

    print(report.to_markdown(), file=output)
    memory_path = write_git_workflow_memory(report)
    print(f"\nMemory: {memory_path}", file=output)
    return 0


def run_git_commit_message(args: argparse.Namespace, output=sys.stdout) -> int:
    try:
        report = build_git_workflow_report(args)
    except Exception as exc:
        ERROR_PRESENTER.print(exc, output=sys.stderr)
        return 1

    print(report.commit_message, file=output)
    return 0


def run_memory_index(args: argparse.Namespace, output=sys.stdout) -> int:
    store = MemoryStore()
    index = ProjectIndex(".")
    summarizer = Summarizer(".")

    try:
        fingerprints = index.scan()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    refreshed = 0
    for fingerprint in fingerprints:
        existing = store.read_file_summary(fingerprint.path)
        if existing is not None and not index.is_summary_stale(existing):
            continue
        store.write_file_summary(summarizer.summarize_file(fingerprint.path, fingerprint))
        refreshed += 1

    project_summary = build_project_summary(fingerprints, Path.cwd())
    store.write_project_summary(project_summary)

    print(f"Memory index refreshed: {refreshed}/{len(fingerprints)} files", file=output)
    print(f"Project summary: {store.project_path}", file=output)
    print(f"File summaries: {store.files_dir}", file=output)
    return 0


def run_memory_context(args: argparse.Namespace, output=sys.stdout) -> int:
    store = MemoryStore()
    builder = ContextBuilder(store)
    bundle = builder.build(args.memory_context)
    rendered = builder.render(bundle)
    path = store.write_context("latest", rendered)

    print(rendered, file=output)
    print(f"Memory context: {path}", file=output)
    return 0


def list_memory_records(store: MemoryStore, output=sys.stdout) -> None:
    project = store.read_project_summary()
    files = store.list_file_summaries()
    decisions = store.list_decisions()
    tasks = store.list_task_memories()

    print("Memory records:", file=output)
    print(f"  Project summary: {'yes' if project is not None else 'no'}", file=output)
    print(f"  File summaries: {len(files)}", file=output)
    print(f"  Decisions: {len(decisions)}", file=output)
    print(f"  Task memories: {len(tasks)}", file=output)
    print(f"  Root: {store.base_dir}", file=output)


def build_project_summary(fingerprints, project_root: Path) -> ProjectSummary:
    paths = [Path(item.path) for item in fingerprints]
    modules = sorted(
        {
            path.parts[0]
            for path in paths
            if path.parts and not path.name.startswith(".")
        }
    )
    entrypoints = [
        item
        for item in ("miniclaudecode/__main__.py", "miniclaudecode/cli.py")
        if any(fingerprint.path == item for fingerprint in fingerprints)
    ]
    test_commands = ["python -m unittest discover"] if any(
        path.parts and path.parts[0] == "tests"
        for path in paths
    ) else []
    capabilities = [
        "Tool Runtime",
        "Planner Executor Evaluator Harness",
        "Git Workflow",
        "Memory and Context Engineering",
    ]
    return ProjectSummary(
        name=project_root.name,
        updated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        modules=modules,
        capabilities=capabilities,
        entrypoints=entrypoints,
        test_commands=test_commands,
    )


def write_git_workflow_memory(report) -> Path:
    store = MemoryStore()
    return store.write_task_memory(report.to_task_memory())


def _main(argv: list[str] | None = None) -> int:
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

    if args.memory_index:
        return run_memory_index(args)

    if args.memory_context:
        return run_memory_context(args)

    if args.list_memory:
        list_memory_records(MemoryStore())
        return 0

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
            ERROR_PRESENTER.print(exc, output=sys.stderr)
            return 1
        return 0

    if args.prompt:
        try:
            agent.run(args.prompt)
            print()
        except Exception as exc:
            ERROR_PRESENTER.print(exc, output=sys.stderr)
            return 1
        return 0

    if args.command == "chat":
        run_interactive(agent)
        return 0

    run_interactive(agent)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except KeyboardInterrupt:
        print("\n(interrupted)", file=sys.stderr)
        return 130
    except SystemExit:
        raise
    except Exception as exc:
        ERROR_PRESENTER.print(exc, output=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
