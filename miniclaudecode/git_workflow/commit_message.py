"""Rule-based commit message generation for Git workflow reports."""

from __future__ import annotations

from dataclasses import dataclass

from miniclaudecode.git_workflow.diff_summary import DiffSummary, FileChange
from miniclaudecode.git_workflow.test_runner import TestRunResult


@dataclass(frozen=True)
class CommitMessageGenerator:
    """Generates deterministic commit messages from local workflow signals."""

    default_subject: str = "Update project files"

    def generate(
        self,
        diff_summary: DiffSummary,
        test_result: TestRunResult | None = None,
        user_summary: str | None = None,
    ) -> str:
        subject = _clean_subject(user_summary) if user_summary else self._build_subject(diff_summary)
        bullets = self._build_bullets(diff_summary)

        if test_result is not None:
            bullets.append(_format_test_bullet(test_result))

        if not bullets:
            return subject

        return "\n".join([subject, "", *[f"- {bullet}" for bullet in bullets]])

    def _build_subject(self, diff_summary: DiffSummary) -> str:
        if not diff_summary.files:
            return "No code changes detected"

        categories = _categorize_files(diff_summary.files)
        if categories["tests"] and len(categories["tests"]) == len(diff_summary.files):
            return "Update tests"
        if categories["docs"] and len(categories["docs"]) == len(diff_summary.files):
            return "Update documentation"
        if categories["source"] and categories["tests"]:
            return "Update implementation and tests"
        if categories["source"]:
            return "Update implementation"
        return self.default_subject

    def _build_bullets(self, diff_summary: DiffSummary) -> list[str]:
        if not diff_summary.files:
            return ["No tracked file changes were found"]

        categories = _categorize_files(diff_summary.files)
        bullets: list[str] = []

        if categories["source"]:
            bullets.append(_format_file_group("Update source files", categories["source"]))
        if categories["tests"]:
            bullets.append(_format_file_group("Update tests", categories["tests"]))
        if categories["docs"]:
            bullets.append(_format_file_group("Update documentation", categories["docs"]))

        uncategorized = categories["other"]
        if uncategorized:
            bullets.append(_format_file_group("Update project files", uncategorized))

        bullets.append(
            f"Diff: {len(diff_summary.files)} files, "
            f"{diff_summary.total_additions} additions, {diff_summary.total_deletions} deletions"
        )
        return bullets


def _categorize_files(files: list[FileChange]) -> dict[str, list[str]]:
    categories: dict[str, list[str]] = {
        "source": [],
        "tests": [],
        "docs": [],
        "other": [],
    }
    for change in files:
        path = change.path.replace("\\", "/")
        if path.startswith("tests/") or "/tests/" in path or path.startswith("test_"):
            categories["tests"].append(change.path)
        elif path.lower().endswith((".md", ".rst", ".txt")) or path.startswith("docs/"):
            categories["docs"].append(change.path)
        elif path.endswith(".py") or path.startswith("miniclaudecode/"):
            categories["source"].append(change.path)
        else:
            categories["other"].append(change.path)
    return categories


def _format_file_group(label: str, files: list[str]) -> str:
    preview = ", ".join(files[:3])
    if len(files) > 3:
        preview += f", and {len(files) - 3} more"
    return f"{label}: {preview}"


def _format_test_bullet(test_result: TestRunResult) -> str:
    command = " ".join(test_result.command)
    status = "passed" if test_result.passed else "failed"
    if test_result.timed_out:
        status = "timed out"
    return f"Tests: `{command}` {status}"


def _clean_subject(subject: str) -> str:
    subject = " ".join(subject.strip().split())
    if not subject:
        return "Update project files"
    return subject[:72]
