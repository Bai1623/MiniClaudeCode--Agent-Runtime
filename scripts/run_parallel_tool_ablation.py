"""Run the deterministic sequential-versus-parallel read-only tool ablation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from miniclaudecode.evals.parallel_ablation import (  # noqa: E402
    run_parallel_read_only_ablation,
    write_parallel_read_only_ablation,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--calls-per-trial", type=int, default=4)
    parser.add_argument("--delay-seconds", type=float, default=0.02)
    parser.add_argument("--output-dir", default=".miniclaudecode/ablations")
    args = parser.parse_args()
    report = run_parallel_read_only_ablation(
        trials=args.trials,
        calls_per_trial=args.calls_per_trial,
        delay_seconds=args.delay_seconds,
    )
    json_path, markdown_path = write_parallel_read_only_ablation(report, args.output_dir)
    print(f"Latency speedup: {report['comparison']['latency_speedup']}x")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
