"""Tests for layered configuration loading."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from miniclaudecode.config import (
    Config,
    HarnessConfig,
    ModelConfig,
    PermissionMode,
    SafetyConfig,
    ToolRuntimeConfig,
    load_config,
)


class TestConfigDefaults(unittest.TestCase):
    def test_config_is_split_into_sections(self):
        config = Config()

        self.assertIsInstance(config.model, ModelConfig)
        self.assertIsInstance(config.tool_runtime, ToolRuntimeConfig)
        self.assertIsInstance(config.safety, SafetyConfig)
        self.assertIsInstance(config.harness, HarnessConfig)
        self.assertEqual(config.model.model, "claude-sonnet-4-20250514")
        self.assertEqual(config.safety.permission_mode, PermissionMode.ASK)

    def test_legacy_constructor_arguments_still_work(self):
        config = Config(
            model="test-model",
            max_turns=7,
            permission_mode="auto",
            max_tool_result_chars=42,
            harness_runs_dir="runs",
            max_repair_rounds=3,
        )

        self.assertEqual(config.model.model, "test-model")
        self.assertEqual(config.max_turns, 7)
        self.assertEqual(config.permission_mode, PermissionMode.AUTO)
        self.assertEqual(config.tool_runtime.max_tool_result_chars, 42)
        self.assertEqual(config.harness.runs_dir, "runs")
        self.assertEqual(config.harness.max_repair_rounds, 3)

    def test_legacy_properties_update_sections(self):
        config = Config()

        config.permission_mode = "plan"
        config.max_turns = 9
        config.allowed_commands = ["git status"]

        self.assertEqual(config.safety.permission_mode, PermissionMode.PLAN)
        self.assertEqual(config.model.max_turns, 9)
        self.assertEqual(config.safety.allowed_commands, ["git status"])


class TestLoadConfig(unittest.TestCase):
    def test_loads_nested_json_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(
                json.dumps({
                    "model": {
                        "model": "file-model",
                        "max_turns": 11,
                    },
                    "tool_runtime": {
                        "max_tool_result_chars": 100,
                    },
                    "safety": {
                        "permission_mode": "plan",
                        "allowed_commands": ["git status"],
                    },
                    "harness": {
                        "runs_dir": "file-runs",
                        "max_repair_rounds": 2,
                    },
                }),
                encoding="utf-8",
            )

            config = load_config(path, env={})

        self.assertEqual(config.model.model, "file-model")
        self.assertEqual(config.model.max_turns, 11)
        self.assertEqual(config.tool_runtime.max_tool_result_chars, 100)
        self.assertEqual(config.safety.permission_mode, PermissionMode.PLAN)
        self.assertEqual(config.safety.allowed_commands, ["git status"])
        self.assertEqual(config.harness.runs_dir, "file-runs")
        self.assertEqual(config.harness.max_repair_rounds, 2)

    def test_precedence_defaults_file_env_cli(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(
                json.dumps({
                    "model": {"model": "file-model", "max_turns": 10},
                    "safety": {"permission_mode": "plan"},
                }),
                encoding="utf-8",
            )

            config = load_config(
                path,
                env={
                    "MINICLAUDECODE_MODEL": "env-model",
                    "MINICLAUDECODE_PERMISSION_MODE": "ask",
                    "MINICLAUDECODE_MAX_REPAIR_ROUNDS": "4",
                },
                cli_overrides={
                    "model.model": "cli-model",
                    "model.max_turns": 3,
                },
            )

        self.assertEqual(config.model.model, "cli-model")
        self.assertEqual(config.model.max_turns, 3)
        self.assertEqual(config.safety.permission_mode, PermissionMode.ASK)
        self.assertEqual(config.harness.max_repair_rounds, 4)

    def test_env_lists_accept_comma_separated_values(self):
        config = load_config(
            env={
                "MINICLAUDECODE_ALLOWED_COMMANDS": "git status, git diff",
                "MINICLAUDECODE_DENIED_PATTERNS": "rm -rf /,git reset --hard",
            },
        )

        self.assertEqual(config.safety.allowed_commands, ["git status", "git diff"])
        self.assertEqual(config.safety.denied_patterns, ["rm -rf /", "git reset --hard"])

    def test_invalid_json_config_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text("not json", encoding="utf-8")

            with self.assertRaises(ValueError):
                load_config(path, env={})


if __name__ == "__main__":
    unittest.main()
