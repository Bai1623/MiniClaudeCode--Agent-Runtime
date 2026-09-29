"""Discovery and uniqueness checks for evaluation case manifests."""

from __future__ import annotations

from pathlib import Path

from .models import EVAL_CASE_SPLITS, EvalCase, EvalCaseValidationError, load_eval_case


class EvalCatalog:
    def __init__(self, root: str | Path = "evals") -> None:
        self.root = Path(root)

    def load(self, *, split: str | None = None) -> list[EvalCase]:
        if split is not None and split not in EVAL_CASE_SPLITS:
            allowed = ", ".join(EVAL_CASE_SPLITS)
            raise EvalCaseValidationError(f"split must be one of: {allowed}.")
        cases_dir = self.root / "cases"
        cases: list[EvalCase] = []
        seen: set[str] = set()
        for path in sorted(cases_dir.glob("*.json")):
            case = load_eval_case(path)
            if case.id in seen:
                raise EvalCaseValidationError(f"Duplicate eval case id: {case.id}")
            seen.add(case.id)
            if split is None or case.split == split:
                cases.append(case)
        return cases
