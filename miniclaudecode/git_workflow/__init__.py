"""Git workflow helpers for engineering handoff."""

from miniclaudecode.git_workflow.commit_message import CommitMessageGenerator
from miniclaudecode.git_workflow.diff_summary import (
    DiffSummary,
    DiffSummaryCollector,
    FileChange,
    parse_numstat,
)
from miniclaudecode.git_workflow.test_runner import (
    DEFAULT_TEST_COMMAND,
    TestRunner,
    TestRunResult,
)
from miniclaudecode.git_workflow.workflow import (
    GitWorkflow,
    GitWorkflowReport,
    merge_diff_summaries,
)
from miniclaudecode.git_workflow.worktree import (
    GitCommandResult,
    GitWorkflowError,
    WorktreeInspector,
    WorktreeStatus,
)

__all__ = [
    "CommitMessageGenerator",
    "DiffSummary",
    "DiffSummaryCollector",
    "FileChange",
    "DEFAULT_TEST_COMMAND",
    "GitCommandResult",
    "GitWorkflowError",
    "GitWorkflow",
    "GitWorkflowReport",
    "TestRunner",
    "TestRunResult",
    "WorktreeInspector",
    "WorktreeStatus",
    "merge_diff_summaries",
    "parse_numstat",
]
