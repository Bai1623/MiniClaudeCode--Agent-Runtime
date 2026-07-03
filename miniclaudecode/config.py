from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class PermissionMode(Enum):
    ASK = "ask"
    AUTO = "auto"
    PLAN = "plan"


@dataclass
class ModelConfig:
    model: str = "claude-sonnet-4-20250514"
    max_turns: int = 30
    max_context_messages: int = 100


@dataclass
class ToolRuntimeConfig:
    max_output_chars: int = 50_000
    max_tool_result_chars: int = 12_000
    tool_result_head_chars: int = 8_000
    tool_result_tail_chars: int = 4_000


@dataclass
class SafetyConfig:
    permission_mode: PermissionMode = PermissionMode.ASK
    allowed_commands: list[str] = field(default_factory=lambda: [
        "ls", "cat", "head", "tail", "wc", "find", "grep", "rg",
        "git status", "git diff", "git log", "git branch",
        "python", "python3", "pip", "npm", "node",
        "echo", "pwd", "which", "env", "date",
    ])
    denied_patterns: list[str] = field(default_factory=lambda: [
        "rm -rf /", "rm -rf ~", "sudo rm",
        "git push --force", "git reset --hard",
        "> /dev/sda", "mkfs", "dd if=",
    ])


@dataclass
class HarnessConfig:
    runs_dir: str = ".miniclaudecode/runs"
    max_repair_rounds: int = 1


@dataclass(init=False)
class Config:
    model: ModelConfig = field(default_factory=ModelConfig)
    tool_runtime: ToolRuntimeConfig = field(default_factory=ToolRuntimeConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    harness: HarnessConfig = field(default_factory=HarnessConfig)

    def __init__(
        self,
        *,
        model: ModelConfig | str | None = None,
        tool_runtime: ToolRuntimeConfig | None = None,
        safety: SafetyConfig | None = None,
        harness: HarnessConfig | None = None,
        max_turns: int | None = None,
        max_context_messages: int | None = None,
        max_output_chars: int | None = None,
        max_tool_result_chars: int | None = None,
        tool_result_head_chars: int | None = None,
        tool_result_tail_chars: int | None = None,
        permission_mode: PermissionMode | str | None = None,
        allowed_commands: list[str] | None = None,
        denied_patterns: list[str] | None = None,
        harness_runs_dir: str | None = None,
        max_repair_rounds: int | None = None,
    ) -> None:
        if isinstance(model, ModelConfig):
            self.model = model
        else:
            self.model = ModelConfig(model=model or ModelConfig().model)

        self.tool_runtime = tool_runtime or ToolRuntimeConfig()
        self.safety = safety or SafetyConfig()
        self.harness = harness or HarnessConfig()

        if max_turns is not None:
            self.model.max_turns = max_turns
        if max_context_messages is not None:
            self.model.max_context_messages = max_context_messages
        if max_output_chars is not None:
            self.tool_runtime.max_output_chars = max_output_chars
        if max_tool_result_chars is not None:
            self.tool_runtime.max_tool_result_chars = max_tool_result_chars
        if tool_result_head_chars is not None:
            self.tool_runtime.tool_result_head_chars = tool_result_head_chars
        if tool_result_tail_chars is not None:
            self.tool_runtime.tool_result_tail_chars = tool_result_tail_chars
        if permission_mode is not None:
            self.safety.permission_mode = _parse_permission_mode(permission_mode)
        if allowed_commands is not None:
            self.safety.allowed_commands = list(allowed_commands)
        if denied_patterns is not None:
            self.safety.denied_patterns = list(denied_patterns)
        if harness_runs_dir is not None:
            self.harness.runs_dir = harness_runs_dir
        if max_repair_rounds is not None:
            self.harness.max_repair_rounds = max_repair_rounds

    @property
    def max_turns(self) -> int:
        return self.model.max_turns

    @max_turns.setter
    def max_turns(self, value: int) -> None:
        self.model.max_turns = value

    @property
    def max_context_messages(self) -> int:
        return self.model.max_context_messages

    @max_context_messages.setter
    def max_context_messages(self, value: int) -> None:
        self.model.max_context_messages = value

    @property
    def max_output_chars(self) -> int:
        return self.tool_runtime.max_output_chars

    @max_output_chars.setter
    def max_output_chars(self, value: int) -> None:
        self.tool_runtime.max_output_chars = value

    @property
    def max_tool_result_chars(self) -> int:
        return self.tool_runtime.max_tool_result_chars

    @max_tool_result_chars.setter
    def max_tool_result_chars(self, value: int) -> None:
        self.tool_runtime.max_tool_result_chars = value

    @property
    def tool_result_head_chars(self) -> int:
        return self.tool_runtime.tool_result_head_chars

    @tool_result_head_chars.setter
    def tool_result_head_chars(self, value: int) -> None:
        self.tool_runtime.tool_result_head_chars = value

    @property
    def tool_result_tail_chars(self) -> int:
        return self.tool_runtime.tool_result_tail_chars

    @tool_result_tail_chars.setter
    def tool_result_tail_chars(self, value: int) -> None:
        self.tool_runtime.tool_result_tail_chars = value

    @property
    def permission_mode(self) -> PermissionMode:
        return self.safety.permission_mode

    @permission_mode.setter
    def permission_mode(self, value: PermissionMode | str) -> None:
        self.safety.permission_mode = _parse_permission_mode(value)

    @property
    def allowed_commands(self) -> list[str]:
        return self.safety.allowed_commands

    @allowed_commands.setter
    def allowed_commands(self, value: list[str]) -> None:
        self.safety.allowed_commands = value

    @property
    def denied_patterns(self) -> list[str]:
        return self.safety.denied_patterns

    @denied_patterns.setter
    def denied_patterns(self, value: list[str]) -> None:
        self.safety.denied_patterns = value


def load_config(
    config_path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
) -> Config:
    """Load config with precedence: defaults < file < env < CLI overrides."""
    config = Config()
    if config_path is not None:
        _apply_mapping(config, _read_config_file(Path(config_path)))
    _apply_env(config, os.environ if env is None else env)
    if cli_overrides:
        _apply_mapping(config, _remove_none_values(dict(cli_overrides)))
    return config


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON config file: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a JSON object: {path}")
    return data


def _apply_env(config: Config, env: Mapping[str, str]) -> None:
    values: dict[str, Any] = {}
    scalar_env = {
        "MINICLAUDECODE_MODEL": "model.model",
        "MINICLAUDECODE_MAX_TURNS": "model.max_turns",
        "MINICLAUDECODE_MAX_CONTEXT_MESSAGES": "model.max_context_messages",
        "MINICLAUDECODE_MAX_OUTPUT_CHARS": "tool_runtime.max_output_chars",
        "MINICLAUDECODE_MAX_TOOL_RESULT_CHARS": "tool_runtime.max_tool_result_chars",
        "MINICLAUDECODE_TOOL_RESULT_HEAD_CHARS": "tool_runtime.tool_result_head_chars",
        "MINICLAUDECODE_TOOL_RESULT_TAIL_CHARS": "tool_runtime.tool_result_tail_chars",
        "MINICLAUDECODE_PERMISSION_MODE": "safety.permission_mode",
        "MINICLAUDECODE_HARNESS_RUNS_DIR": "harness.runs_dir",
        "MINICLAUDECODE_MAX_REPAIR_ROUNDS": "harness.max_repair_rounds",
    }
    for env_name, dotted_key in scalar_env.items():
        if env_name in env:
            values[dotted_key] = env[env_name]
    if "MINICLAUDECODE_ALLOWED_COMMANDS" in env:
        values["safety.allowed_commands"] = _split_csv(env["MINICLAUDECODE_ALLOWED_COMMANDS"])
    if "MINICLAUDECODE_DENIED_PATTERNS" in env:
        values["safety.denied_patterns"] = _split_csv(env["MINICLAUDECODE_DENIED_PATTERNS"])
    _apply_mapping(config, values)


def _apply_mapping(config: Config, values: Mapping[str, Any]) -> None:
    for key, value in values.items():
        if isinstance(value, Mapping):
            _apply_section(config, key, value)
        else:
            _apply_value(config, key, value)


def _apply_section(config: Config, section: str, values: Mapping[str, Any]) -> None:
    for key, value in values.items():
        _apply_value(config, f"{section}.{key}", value)


def _apply_value(config: Config, key: str, value: Any) -> None:
    if key in {"model", "model.model"}:
        config.model.model = str(value)
    elif key in {"max_turns", "model.max_turns"}:
        config.model.max_turns = _parse_int(key, value)
    elif key in {"max_context_messages", "model.max_context_messages"}:
        config.model.max_context_messages = _parse_int(key, value)
    elif key in {"max_output_chars", "tool_runtime.max_output_chars"}:
        config.tool_runtime.max_output_chars = _parse_int(key, value)
    elif key in {"max_tool_result_chars", "tool_runtime.max_tool_result_chars"}:
        config.tool_runtime.max_tool_result_chars = _parse_int(key, value)
    elif key in {"tool_result_head_chars", "tool_runtime.tool_result_head_chars"}:
        config.tool_runtime.tool_result_head_chars = _parse_int(key, value)
    elif key in {"tool_result_tail_chars", "tool_runtime.tool_result_tail_chars"}:
        config.tool_runtime.tool_result_tail_chars = _parse_int(key, value)
    elif key in {"permission_mode", "safety.permission_mode"}:
        config.safety.permission_mode = _parse_permission_mode(value)
    elif key in {"allowed_commands", "safety.allowed_commands"}:
        config.safety.allowed_commands = _parse_string_list(key, value)
    elif key in {"denied_patterns", "safety.denied_patterns"}:
        config.safety.denied_patterns = _parse_string_list(key, value)
    elif key in {"harness_runs_dir", "harness.runs_dir"}:
        config.harness.runs_dir = str(value)
    elif key in {"max_repair_rounds", "harness.max_repair_rounds"}:
        config.harness.max_repair_rounds = _parse_int(key, value)


def _parse_permission_mode(value: PermissionMode | str) -> PermissionMode:
    if isinstance(value, PermissionMode):
        return value
    return PermissionMode(str(value))


def _parse_int(key: str, value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Config value '{key}' must be an integer.") from exc


def _parse_string_list(key: str, value: Any) -> list[str]:
    if isinstance(value, str):
        return _split_csv(value)
    if isinstance(value, list):
        return [str(item) for item in value]
    raise ValueError(f"Config value '{key}' must be a list or comma-separated string.")


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _remove_none_values(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
