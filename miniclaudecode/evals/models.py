"""Versioned, portable data contracts for offline coding-agent evaluations."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EVAL_CASE_SCHEMA_VERSION = 1
_CASE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_CASE_KEYS = {
    "schema_version",
    "id",
    "task",
    "fixture",
    "success_criteria",
    "graders",
    "budget",
    "tags",
}
_BUDGET_KEYS = {
    "max_model_calls",
    "max_tool_calls",
    "max_input_tokens",
    "max_output_tokens",
    "timeout_seconds",
    "max_cost_usd",
}


class EvalCaseValidationError(ValueError):
    """Raised when an eval manifest is invalid or not portable."""


@dataclass(frozen=True)
class EvalBudget:
    max_model_calls: int = 20
    max_tool_calls: int = 100
    max_input_tokens: int = 200_000
    max_output_tokens: int = 40_000
    timeout_seconds: int = 600
    max_cost_usd: float | None = None

    @classmethod
    def from_dict(cls, values: dict[str, Any] | None) -> EvalBudget:
        if values is None:
            values = {}
        if not isinstance(values, dict):
            raise EvalCaseValidationError("budget must be an object.")
        _reject_unknown_keys("budget", values, _BUDGET_KEYS)
        try:
            budget = cls(**values)
        except TypeError as exc:
            raise EvalCaseValidationError("budget contains invalid values.") from exc
        for name in (
            "max_model_calls",
            "max_tool_calls",
            "max_input_tokens",
            "max_output_tokens",
            "timeout_seconds",
        ):
            _require_positive_integer(f"budget.{name}", getattr(budget, name))
        if budget.max_cost_usd is not None and (
            isinstance(budget.max_cost_usd, bool)
            or not isinstance(budget.max_cost_usd, (int, float))
            or budget.max_cost_usd <= 0
        ):
            raise EvalCaseValidationError("budget.max_cost_usd must be a positive number.")
        return budget

    def to_dict(self) -> dict[str, int | float | None]:
        return {
            "max_model_calls": self.max_model_calls,
            "max_tool_calls": self.max_tool_calls,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "timeout_seconds": self.timeout_seconds,
            "max_cost_usd": self.max_cost_usd,
        }


@dataclass(frozen=True)
class GraderSpec:
    kind: str
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> GraderSpec:
        _reject_unknown_keys("grader", values, {"kind", "config"})
        kind = _require_non_empty_string("grader.kind", values.get("kind"))
        config = values.get("config", {})
        if not isinstance(config, dict):
            raise EvalCaseValidationError("grader.config must be an object.")
        return cls(kind=kind, config=dict(config))

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "config": dict(self.config)}


@dataclass(frozen=True)
class EvalCase:
    id: str
    task: str
    fixture: str
    success_criteria: tuple[str, ...]
    graders: tuple[GraderSpec, ...]
    budget: EvalBudget = field(default_factory=EvalBudget)
    tags: tuple[str, ...] = ()
    schema_version: int = EVAL_CASE_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> EvalCase:
        _reject_unknown_keys("eval case", values, _CASE_KEYS)
        schema_version = values.get("schema_version")
        if isinstance(schema_version, bool) or schema_version != EVAL_CASE_SCHEMA_VERSION:
            raise EvalCaseValidationError(
                f"Unsupported eval case schema_version: {schema_version!r}; "
                f"expected {EVAL_CASE_SCHEMA_VERSION}."
            )
        case_id = _require_non_empty_string("id", values.get("id"))
        if not _CASE_ID_PATTERN.fullmatch(case_id):
            raise EvalCaseValidationError(
                "id must use lowercase letters, digits, dots, underscores, or hyphens."
            )
        criteria = _string_tuple("success_criteria", values.get("success_criteria"), required=True)
        raw_graders = values.get("graders")
        if not isinstance(raw_graders, list) or not raw_graders:
            raise EvalCaseValidationError("graders must be a non-empty list.")
        if not all(isinstance(item, dict) for item in raw_graders):
            raise EvalCaseValidationError("every grader must be an object.")
        tags = _string_tuple("tags", values.get("tags", []), required=False)
        if len(set(tags)) != len(tags):
            raise EvalCaseValidationError("tags must not contain duplicates.")
        return cls(
            id=case_id,
            task=_require_non_empty_string("task", values.get("task")),
            fixture=_validate_fixture_reference(values.get("fixture")),
            success_criteria=criteria,
            graders=tuple(GraderSpec.from_dict(item) for item in raw_graders),
            budget=EvalBudget.from_dict(values.get("budget")),
            tags=tags,
            schema_version=schema_version,
        )

    def resolve_fixture(self, manifest_dir: Path) -> Path:
        fixture_root = manifest_dir.parent / "fixtures"
        path = (fixture_root / self.fixture).resolve()
        if fixture_root.resolve() not in (path, *path.parents):
            raise EvalCaseValidationError(f"fixture escapes the fixture root: {self.fixture}")
        return path

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "task": self.task,
            "fixture": self.fixture,
            "success_criteria": list(self.success_criteria),
            "graders": [grader.to_dict() for grader in self.graders],
            "budget": self.budget.to_dict(),
            "tags": list(self.tags),
        }


def load_eval_case(path: str | Path) -> EvalCase:
    manifest_path = Path(path)
    try:
        values = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalCaseValidationError(f"Invalid eval case JSON: {manifest_path}") from exc
    if not isinstance(values, dict):
        raise EvalCaseValidationError("eval case manifest must contain a JSON object.")
    case = EvalCase.from_dict(values)
    fixture_path = case.resolve_fixture(manifest_path.parent)
    if not fixture_path.is_dir():
        raise EvalCaseValidationError(f"fixture directory does not exist: {fixture_path}")
    return case


def _reject_unknown_keys(label: str, values: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise EvalCaseValidationError(f"Unknown {label} fields: {', '.join(unknown)}")


def _require_non_empty_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvalCaseValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _require_positive_integer(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvalCaseValidationError(f"{name} must be a positive integer.")


def _string_tuple(name: str, value: Any, *, required: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or (required and not value):
        suffix = "non-empty " if required else ""
        raise EvalCaseValidationError(f"{name} must be a {suffix}list of strings.")
    return tuple(_require_non_empty_string(name, item) for item in value)


def _validate_fixture_reference(value: Any) -> str:
    fixture = _require_non_empty_string("fixture", value)
    path = Path(fixture)
    if path.is_absolute() or ".." in path.parts:
        raise EvalCaseValidationError("fixture must be a portable path below evals/fixtures.")
    return path.as_posix()
