"""Reproducibility manifest for offline evaluation batches."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from miniclaudecode import __version__
from miniclaudecode.config import Config

from .models import EvalCase

EXPERIMENT_MANIFEST_SCHEMA_VERSION = 1
ISOLATED_WORKSPACE_PLACEHOLDER = "<isolated-trial-workspace>"


class ExperimentManifestBuilder:
    """Capture code, configuration, case, and runtime identity without secrets."""

    def __init__(
        self,
        *,
        config: Config | None = None,
        project_root: str | Path = ".",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.project_root = Path(project_root).resolve()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def build(self, case: EvalCase, *, trial_count: int) -> dict[str, Any]:
        case_values = case.to_dict()
        config_values = _config_values(self.config)
        return {
            "schema_version": EXPERIMENT_MANIFEST_SCHEMA_VERSION,
            "created_at": _timestamp(self.clock()),
            "source": {"git": _git_identity(self.project_root)},
            "agent": {
                "package": "miniclaudecode",
                "version": __version__,
                "model": self.config.model.model if self.config is not None else None,
            },
            "configuration": {
                "available": self.config is not None,
                "sha256": _fingerprint(config_values) if config_values is not None else None,
                "values": config_values,
            },
            "runtime": {
                "python_version": platform.python_version(),
                "python_implementation": platform.python_implementation(),
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
            },
            "evaluation": {
                "case_id": case.id,
                "case_schema_version": case.schema_version,
                "case_sha256": _fingerprint(case_values),
                "fixture": case.fixture,
                "requested_trials": trial_count,
                "budget": case.budget.to_dict(),
            },
        }


def _config_values(config: Config | None) -> dict[str, Any] | None:
    if config is None:
        return None
    values = _json_safe(asdict(config))
    if not isinstance(values, dict):
        raise TypeError("Config snapshot must be a JSON object.")
    safety = values.get("safety")
    if isinstance(safety, dict):
        safety["workspace_root"] = ISOLATED_WORKSPACE_PLACEHOLDER
    return values


def _git_identity(project_root: Path) -> dict[str, Any]:
    commit = _run_git(project_root, ["rev-parse", "HEAD"])
    if commit is None:
        return {
            "available": False,
            "commit_sha": None,
            "branch": None,
            "dirty": None,
        }
    branch = _run_git(project_root, ["branch", "--show-current"])
    status = _run_git(project_root, ["status", "--porcelain", "--untracked-files=normal"])
    return {
        "available": True,
        "commit_sha": commit,
        "branch": branch or None,
        "dirty": bool(status),
    }


def _run_git(project_root: Path, arguments: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _fingerprint(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
