"""Tests for user-facing error presentation."""

from __future__ import annotations

import unittest
from io import StringIO

from jsonschema import ValidationError

from miniclaudecode.errors import ErrorPresenter


class ApiConnectionError(Exception):
    pass


class RateLimitError(Exception):
    pass


class NotFoundError(Exception):
    pass


class TestErrorPresenter(unittest.TestCase):
    def render(self, exc: BaseException) -> str:
        output = StringIO()
        ErrorPresenter().print(exc, output=output)
        return output.getvalue()

    def test_missing_api_key_message_includes_fix_actions(self):
        text = self.render(ValueError("The api_key client option must be set"))

        self.assertIn("Anthropic API key is missing", text)
        self.assertIn("ANTHROPIC_API_KEY", text)
        self.assertIn("doctor", text)

    def test_network_failure_message_is_actionable(self):
        text = self.render(ApiConnectionError("Connection timed out"))

        self.assertIn("Network request failed", text)
        self.assertIn("Check your network", text)
        self.assertIn("try again", text)

    def test_rate_limit_message_is_actionable(self):
        text = self.render(RateLimitError("rate_limit_error"))

        self.assertIn("Rate limit reached", text)
        self.assertIn("wait", text)
        self.assertIn("retry", text)

    def test_model_error_message_points_to_model_configuration(self):
        text = self.render(NotFoundError("model: bad-model not found"))

        self.assertIn("Model is unavailable or invalid", text)
        self.assertIn("--model", text)
        self.assertIn("MINICLAUDECODE_MODEL", text)

    def test_json_schema_error_message_explains_tool_input_problem(self):
        text = self.render(ValidationError("'path' is a required property"))

        self.assertIn("Tool input did not match its JSON schema", text)
        self.assertIn("tool generated malformed input", text)
        self.assertIn("retry", text)

    def test_unknown_error_uses_concise_fallback(self):
        text = self.render(RuntimeError("boom"))

        self.assertIn("Unexpected error", text)
        self.assertIn("miniClaudeCode doctor", text)
        self.assertIn("RuntimeError: boom", text)


if __name__ == "__main__":
    unittest.main()
