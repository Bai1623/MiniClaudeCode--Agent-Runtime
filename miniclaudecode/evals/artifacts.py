"""Durable artifacts for isolated evaluation trials."""

from __future__ import annotations

import hashlib
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
        return self.create_scoped_trial(case_id, trial_id)

    def create_batch(self, case_id: str, batch_id: str) -> Path:
        _validate_artifact_id("batch_id", batch_id)
        batch_dir = self.base_dir / case_id / batch_id
        batch_dir.mkdir(parents=True, exist_ok=False)
        return batch_dir

    def create_scoped_trial(
        self,
        case_id: str,
        trial_id: str,
        *,
        batch_id: str | None = None,
    ) -> Path:
        _validate_artifact_id("trial_id", trial_id)
        parent = self.base_dir / case_id
        if batch_id is not None:
            _validate_artifact_id("batch_id", batch_id)
            parent /= batch_id
        trial_dir = parent / trial_id
        trial_dir.mkdir(parents=True, exist_ok=False)
        return trial_dir

    def write_result(self, trial_dir: Path, result: dict[str, Any]) -> Path:
        return self.write_json(trial_dir / "eval_result.json", result)

    def write_json(self, path: Path, value: Any) -> Path:
        return self.write_text(
            path,
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        )

    def write_jsonl(self, path: Path, values: list[dict[str, Any]]) -> Path:
        content = "".join(
            json.dumps(value, ensure_ascii=False) + "\n"
            for value in values
        )
        return self.write_text(path, content)

    def write_text(self, path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            content,
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    def write_index(self, trial_dir: Path) -> Path:
        entries = []
        for path in sorted(trial_dir.rglob("*")):
            if not path.is_file() or path.name == "artifacts.json":
                continue
            content = path.read_bytes()
            entries.append({
                "path": path.relative_to(trial_dir).as_posix(),
                "media_type": _media_type(path),
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            })
        return self.write_json(
            trial_dir / "artifacts.json",
            {
                "schema_version": 1,
                "artifact_count": len(entries),
                "artifacts": entries,
            },
        )

    def write_batch_summary(self, batch_dir: Path, summary: dict[str, Any]) -> Path:
        return self.write_json(batch_dir / "trials_summary.json", summary)

    def write_experiment_manifest(self, batch_dir: Path, manifest: dict[str, Any]) -> Path:
        return self.write_json(batch_dir / "experiment_manifest.json", manifest)


def _media_type(path: Path) -> str:
    if path.suffix == ".json":
        return "application/json"
    if path.suffix == ".jsonl":
        return "application/x-ndjson"
    if path.suffix == ".diff":
        return "text/x-diff"
    return "text/plain"


def _validate_artifact_id(name: str, value: str) -> None:
    if not _TRIAL_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a portable filename using letters, digits, ._-.")
