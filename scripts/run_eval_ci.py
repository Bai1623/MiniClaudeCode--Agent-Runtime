"""Run deterministic, API-free calibration checks for development eval graders."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from miniclaudecode.evals import (  # noqa: E402
    CandidateExecution,
    EvalArtifactStore,
    EvalBatchRunner,
    EvalCatalog,
    EvalRunner,
)

RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")
RUN_ATTEMPT = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
BATCH_ID = f"ci-{RUN_ID}-{RUN_ATTEMPT}-{uuid.uuid4().hex[:8]}"


class NoOpExecutor:
    """Leave the fixture unchanged so graders must reject an unfixed task."""

    def execute(self, case: Any, workspace: Path, timeout_seconds: int, artifact_dir: Path):
        return CandidateExecution(text="Deterministic CI no-op calibration; no model was called.")


def main() -> int:
    artifact_root = REPOSITORY_ROOT / ".miniclaudecode" / "evals" / "ci-validation"
    store = EvalArtifactStore(artifact_root)
    batch_runner = EvalBatchRunner(EvalRunner(artifact_store=store))
    case_summaries: list[dict[str, Any]] = []

    for case in EvalCatalog(REPOSITORY_ROOT / "evals").load(split="development"):
        batch = batch_runner.run(
            case,
            manifest_dir=REPOSITORY_ROOT / "evals" / "cases",
            executor_factory=NoOpExecutor,
            trial_count=1,
            batch_id=BATCH_ID,
        )
        trial = batch.trials[0]
        grader_path = trial.artifact_path.parent / "grader_results.json"
        grader_report = json.loads(grader_path.read_text(encoding="utf-8"))
        results = {item["grader"]: item["passed"] for item in grader_report["results"]}
        checks = {
            "no_op_rejected": results.get("no_op") is False,
            "known_regression_detected": results.get("fail_to_pass") is False,
            "existing_behavior_preserved": results.get("pass_to_pass") is True,
            "no_infrastructure_error": trial.status != "infrastructure_error",
        }
        case_summaries.append(
            {
                "case_id": case.id,
                "status": "passed" if all(checks.values()) else "failed",
                "checks": checks,
                "batch_summary": batch.summary_path.relative_to(artifact_root).as_posix(),
                "experiment_manifest": batch.manifest_path.relative_to(artifact_root).as_posix(),
                "trial_result": trial.artifact_path.relative_to(artifact_root).as_posix(),
            }
        )

    summary = {
        "schema_version": 1,
        "mode": "deterministic_no_op_grader_calibration",
        "api_required": False,
        "passed": bool(case_summaries) and all(item["status"] == "passed" for item in case_summaries),
        "case_count": len(case_summaries),
        "cases": case_summaries,
    }
    summary_path = artifact_root / "ci_validation_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
