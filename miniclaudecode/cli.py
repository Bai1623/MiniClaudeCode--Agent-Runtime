"""CLI entry point -- distilled from Claude Code's 20+ subcommand CLI.

Original: argparse with subcommands for summary, manifest, parity-audit, bootstrap,
turn-loop, remote-mode, ssh-mode, etc., plus an Ink/React terminal UI.

Mini version: simple interactive REPL with 3 commands: chat (default), tools, help.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import Config, PermissionMode
from .harness.artifacts import ArtifactStore
from .harness.evaluator import Evaluator
from .harness.executor import Executor
from .harness.planner import Planner
from .harness.report import FinalReportGenerator
from .harness.task_harness import TaskHarness
from .memory import ContextBuilder, MemoryStore, ProjectIndex, ProjectSummary, Summarizer
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
        memory_store=MemoryStore(),
    )
    result = harness.run(
        request=args.prompt,
        goal=args.prompt,
        spec=args.harness_spec,
        tasks=default_harness_tasks(args.prompt, args.harness_task),
    )
    git_report = build_git_workflow_report(args)
    FinalReportGenerator().write(store, result, git_report=git_report)

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
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(report.to_markdown(), file=output)
    memory_path = write_git_workflow_memory(report)
    print(f"\nMemory: {memory_path}", file=output)
    return 0


def run_git_commit_message(args: argparse.Namespace, output=sys.stdout) -> int:
    try:
        report = build_git_workflow_report(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_runs:
        list_harness_runs(ArtifactStore())
        return 0

    if args.run_harness:
        return run_harness(args)

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
