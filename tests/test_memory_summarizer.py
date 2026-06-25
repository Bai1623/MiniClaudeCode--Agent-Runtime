"""Tests for deterministic project file summaries."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from miniclaudecode.memory import FileFingerprint, Summarizer


class TestSummarizer(unittest.TestCase):
    def test_python_summary_extracts_top_level_symbols_and_docstring(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "module.py"
            path.write_text(
                '"""Runtime orchestration."""\n'
                "class AgentLoop:\n"
                "    def run(self):\n"
                "        return None\n\n"
                "async def execute():\n"
                "    return None\n",
                encoding="utf-8",
            )

            summary = Summarizer(tmpdir).summarize_file("module.py")

            self.assertEqual(summary.language, "python")
            self.assertEqual(
                summary.symbols,
                ["class AgentLoop", "function execute"],
            )
            self.assertIn("Classes: AgentLoop", summary.summary)
            self.assertIn("Functions: execute", summary.summary)
            self.assertIn("Runtime orchestration.", summary.summary)

    def test_invalid_python_falls_back_to_text_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "broken.py"
            path.write_text("def broken(:\n    pass\n", encoding="utf-8")

            summary = Summarizer(tmpdir).summarize_file(path)

            self.assertEqual(summary.symbols, [])
            self.assertIn("syntax could not be parsed", summary.summary)
            self.assertIn("def broken(:", summary.summary)

    def test_markdown_summary_extracts_headings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "README.md"
            path.write_text(
                "# miniClaudeCode\n\n## Runtime\n\n### Tests\n",
                encoding="utf-8",
            )

            summary = Summarizer(tmpdir).summarize_file("README.md")

            self.assertEqual(summary.language, "markdown")
            self.assertEqual(
                summary.symbols,
                [
                    "heading miniClaudeCode",
                    "heading Runtime",
                    "heading Tests",
                ],
            )
            self.assertIn("3 headings", summary.summary)

    def test_plain_text_summary_uses_non_empty_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "requirements.txt"
            path.write_text(
                "anthropic>=0.42.0\n\njsonschema>=4.0.0\n",
                encoding="utf-8",
            )

            summary = Summarizer(tmpdir).summarize_file("requirements.txt")

            self.assertEqual(summary.language, "text")
            self.assertEqual(summary.symbols, [])
            self.assertIn("anthropic>=0.42.0 | jsonschema>=4.0.0", summary.summary)

    def test_long_summary_is_truncated_to_configured_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "notes.txt"
            path.write_text("A" * 200, encoding="utf-8")

            summary = Summarizer(
                tmpdir,
                max_summary_chars=50,
            ).summarize_file("notes.txt")

            self.assertEqual(len(summary.summary), 50)
            self.assertTrue(summary.summary.endswith("[truncated]"))

    def test_binary_file_returns_safe_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "data.txt"
            path.write_bytes(b"text\0binary")

            summary = Summarizer(tmpdir).summarize_file("data.txt")

            self.assertEqual(summary.symbols, [])
            self.assertIn("content was not indexed", summary.summary)

    def test_non_utf8_file_returns_safe_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "legacy.txt"
            path.write_bytes(b"\xff\xfe\xfa")

            summary = Summarizer(tmpdir).summarize_file("legacy.txt")

            self.assertIn("non-UTF-8", summary.summary)

    def test_empty_file_returns_explicit_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "empty.txt"
            path.write_text("", encoding="utf-8")

            summary = Summarizer(tmpdir).summarize_file("empty.txt")

            self.assertEqual(summary.summary, "Empty text file.")
            self.assertEqual(summary.size_bytes, 0)

    def test_rejects_fingerprint_for_a_different_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "actual.py"
            path.write_text("value = 1", encoding="utf-8")
            fingerprint = FileFingerprint(
                path="other.py",
                sha256="abc",
                size_bytes=1,
                updated_at="2026-06-25T00:00:00Z",
            )

            with self.assertRaisesRegex(ValueError, "does not match"):
                Summarizer(tmpdir).summarize_file(path, fingerprint)

    def test_refreshes_stale_fingerprint_before_building_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "module.py"
            path.write_text("value = 1", encoding="utf-8")
            summarizer = Summarizer(tmpdir)
            old_fingerprint = summarizer.index.compute_file_fingerprint(path)
            path.write_text("value = 200", encoding="utf-8")

            summary = summarizer.summarize_file(path, old_fingerprint)
            current = summarizer.index.compute_file_fingerprint(path)

            self.assertEqual(summary.sha256, current.sha256)
            self.assertEqual(summary.size_bytes, current.size_bytes)

    def test_constructor_rejects_invalid_limits(self):
        with self.assertRaisesRegex(ValueError, "max_summary_chars"):
            Summarizer(max_summary_chars=0)
        with self.assertRaisesRegex(ValueError, "max_text_lines"):
            Summarizer(max_text_lines=0)


if __name__ == "__main__":
    unittest.main()
