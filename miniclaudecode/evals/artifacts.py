"""Durable artifacts for isolated evaluation trials."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_TRIAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class EvalArtifactStore:
    """Create collision-safe trial directories and atomically write results."""

    def __init__(self, base_dir: str | Path = ".miniclaudecode/evals") -> None:
        self.base_dir = Path(base_dir)

    def create_trial(self, case_id: str, trial_id: str) -> Path:
        if not _TRIAL_ID_PATTERN.fullmatch(trial_id):
            raise ValueError("trial_id must be a portable filename using letters, digits, ._-.")
        trial_dir = self.base_dir / case_id / trial_id
        trial_dir.mkdir(parents=True, exist_ok=False)
        return trial_dir

    def write_result(self, trial_dir: Path, result: dict[str, Any]) -> Path:
        path = trial_dir / "eval_result.json"
        temporary = trial_dir / ".eval_result.json.tmp"
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path
