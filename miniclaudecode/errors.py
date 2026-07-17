"""User-facing error presentation helpers."""

from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass
from typing import TextIO

from jsonschema import ValidationError


@dataclass(frozen=True)
class PresentedError:
    """A concise, actionable version of a lower-level exception."""

    title: str
    cause: str
    actions: tuple[str, ...]
    details: str | None = None


class ErrorPresenter:
    """Translate implementation exceptions into terminal-friendly guidance."""

    def present(self, exc: BaseException) -> PresentedError:
        class_name = exc.__class__.__name__
        module = exc.__class__.__module__
        message = str(exc).strip()
        haystack = f"{module} {class_name} {message}".lower()

        if self._is_missing_api_key(haystack):
            return PresentedError(
                title="Anthropic API key is missing",
                cause="miniClaudeCode could not create or use the Anthropic client because no API key was configured.",
                actions=(
                    "Set ANTHROPIC_API_KEY in your shell.",
                    "Run `miniClaudeCode doctor` to verify the key is visible to the CLI.",
                    "If you use a config file or process manager, restart it after updating the environment.",
                ),
                details=self._details(exc),
            )

        if self._is_rate_limit(haystack):
            return PresentedError(
                title="Rate limit reached",
                cause="The model provider rejected the request because the current rate or quota limit was exceeded.",
                actions=(
                    "wait a short time and retry the command.",
                    "Reduce concurrent runs or lower request volume.",
                    "Check your Anthropic account limits if this keeps happening.",
                ),
                details=self._details(exc),
            )

        if self._is_model_error(haystack):
            return PresentedError(
                title="Model is unavailable or invalid",
                cause="The configured model name was rejected or is not available to this API key.",
                actions=(
                    "Check the configured model in your JSON config file.",
                    "Override it with `--model <model-name>` for a single run.",
                    "Set MINICLAUDECODE_MODEL if this is deployed through environment variables.",
                ),
                details=self._details(exc),
            )

        if self._is_network_error(haystack):
            return PresentedError(
                title="Network request failed",
                cause="miniClaudeCode could not reach the model provider or the request timed out.",
                actions=(
                    "Check your network connection, proxy, VPN, and DNS settings.",
                    "try again after the connection is stable.",
                    "If this happens in CI, verify outbound network access is allowed.",
                ),
                details=self._details(exc),
            )

        if isinstance(exc, ValidationError) or self._is_schema_error(haystack):
            return PresentedError(
                title="Tool input did not match its JSON schema",
                cause="The model or tool generated malformed input that failed schema validation.",
                actions=(
                    "retry the task; transient malformed tool input often resolves on the next attempt.",
                    "If it repeats, simplify the prompt or inspect the tool schema.",
                    "For custom tools, verify the manifest schema and required fields.",
                ),
                details=self._details(exc),
            )

        if self._is_config_json_error(haystack):
            return PresentedError(
                title="Configuration file is invalid",
                cause="The selected config file could not be parsed as the expected JSON object.",
                actions=(
                    "Validate the JSON syntax in the config file.",
                    "Make sure the top-level value is an object.",
                    "Run `miniClaudeCode doctor --config <path>` after fixing it.",
                ),
                details=self._details(exc),
            )

        return PresentedError(
            title="Unexpected error",
            cause="miniClaudeCode hit an error that is not yet classified.",
            actions=(
                "Run `miniClaudeCode doctor` to check the local setup.",
                "Retry with a smaller prompt or fewer enabled tools if the failure happened during a run.",
                "If it repeats, capture this message and the command you ran for debugging.",
            ),
            details=self._details(exc),
        )

    def format(self, exc: BaseException) -> str:
        presented = self.present(exc)
        lines = [
            f"Error: {presented.title}",
            "",
            f"Why: {presented.cause}",
            "",
            "How to fix:",
        ]
        lines.extend(f"  {index}. {action}" for index, action in enumerate(presented.actions, 1))
        if presented.details:
            lines.extend(["", f"Details: {presented.details}"])
        return "\n".join(lines)

    def print(self, exc: BaseException, output: TextIO) -> None:
        print(self.format(exc), file=output)

    @staticmethod
    def _details(exc: BaseException) -> str:
        message = str(exc).strip()
        if not message:
            message = "(no exception message)"
        message = " ".join(message.split())
        return f"{exc.__class__.__name__}: {message}"

    @staticmethod
    def _is_missing_api_key(haystack: str) -> bool:
        return (
            "api_key" in haystack
            or "api key" in haystack
            or ("anthropic" in haystack and "authentication" in haystack)
            or ("anthropic" in haystack and "unauthorized" in haystack)
            or "401" in haystack
        )

    @staticmethod
    def _is_network_error(haystack: str) -> bool:
        markers = (
            "apiconnectionerror",
            "connection",
            "connecterror",
            "network",
            "timed out",
            "timeout",
            "dns",
            "temporary failure",
        )
        return any(marker in haystack for marker in markers)

    @staticmethod
    def _is_rate_limit(haystack: str) -> bool:
        return "ratelimit" in haystack or "rate limit" in haystack or "rate_limit" in haystack or "429" in haystack

    @staticmethod
    def _is_model_error(haystack: str) -> bool:
        if "model" not in haystack:
            return False
        markers = ("notfound", "not found", "invalid", "unavailable", "does not exist", "404")
        return any(marker in haystack for marker in markers)

    @staticmethod
    def _is_schema_error(haystack: str) -> bool:
        markers = (
            "jsonschema",
            "schema",
            "validationerror",
            "validation_error",
            "invalid input for tool",
        )
        return any(marker in haystack for marker in markers)

    @staticmethod
    def _is_config_json_error(haystack: str) -> bool:
        return (
            "invalid json config file" in haystack
            or "config file must contain a json object" in haystack
            or (os.sep in haystack and "json" in haystack and "config" in haystack)
        )


def format_exception(exc: BaseException) -> str:
    """Return a user-facing explanation for an exception."""
    return ErrorPresenter().format(exc)


def short_exception(exc: BaseException) -> str:
    """Return a one-line summary for places that cannot render a full block."""
    formatted = ErrorPresenter().format(exc)
    return textwrap.shorten(" ".join(formatted.split()), width=240, placeholder="...")
