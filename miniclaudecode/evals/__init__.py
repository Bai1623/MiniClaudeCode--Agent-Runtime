"""Offline evaluation case definitions and catalog loading."""

from .artifacts import EvalArtifactStore
from .catalog import EvalCatalog
from .comparison import compare_eval_batches, render_comparison_markdown, write_comparison_reports
from .graders import (
    EvalGradeReport,
    GradeContext,
    GradeResult,
    GraderRegistry,
    changed_workspace_files,
)
from .manifest import ExperimentManifestBuilder
from .metrics import build_batch_metrics
from .models import (
    EVAL_CASE_SPLITS,
    EvalBudget,
    EvalCase,
    EvalCaseValidationError,
    GraderSpec,
    load_eval_case,
)
from .runner import (
    AgentCandidateExecutor,
    CandidateExecution,
    CandidateExecutor,
    EvalBatchResult,
    EvalBatchRunner,
    EvalRunner,
    EvalRunResult,
)

__all__ = [
    "EvalBudget",
    "EVAL_CASE_SPLITS",
    "EvalArtifactStore",
    "EvalCase",
    "EvalCaseValidationError",
    "EvalCatalog",
    "compare_eval_batches",
    "render_comparison_markdown",
    "write_comparison_reports",
    "EvalGradeReport",
    "ExperimentManifestBuilder",
    "EvalBatchResult",
    "EvalBatchRunner",
    "EvalRunResult",
    "EvalRunner",
    "GradeContext",
    "GradeResult",
    "GraderRegistry",
    "GraderSpec",
    "AgentCandidateExecutor",
    "CandidateExecution",
    "CandidateExecutor",
    "changed_workspace_files",
    "build_batch_metrics",
    "load_eval_case",
]
