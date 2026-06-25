"""Deterministic summaries for project files."""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

from miniclaudecode.memory.project_index import FileFingerprint, ProjectIndex
from miniclaudecode.memory.records import FileSummary


LANGUAGES = {
    ".cfg": "config",
    ".css": "css",
    ".html": "html",
    ".ini": "config",
    ".js": "javascript",
    ".json": "json",
    ".jsx": "javascript",
    ".md": "markdown",
    ".py": "python",
    ".rst": "restructuredtext",
    ".sh": "shell",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".txt": "text",
    ".yaml": "yaml",
    ".yml": "yaml",
}
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")


class Summarizer:
    """Builds compact, reusable file summaries without an LLM."""

    def __init__(
        self,
        project_root: str | Path = ".",
        max_summary_chars: int = 2_000,
        max_text_lines: int = 20,
    ) -> None:
        if max_summary_chars <= 0:
            raise ValueError("max_summary_chars must be positive.")
        if max_text_lines <= 0:
            raise ValueError("max_text_lines must be positive.")
        self.index = ProjectIndex(project_root)
        self.max_summary_chars = max_summary_chars
        self.max_text_lines = max_text_lines

    def summarize_file(
        self,
        path: str | Path,
        fingerprint: FileFingerprint | None = None,
    ) -> FileSummary:
        relative_path, absolute_path = self.index._resolve_file(path)
        if fingerprint is not None and fingerprint.path != relative_path.as_posix():
            raise ValueError(
                "Fingerprint path does not match the file being summarized."
            )
        language = _detect_language(absolute_path)
        content_bytes = absolute_path.read_bytes()
        current = fingerprint
        if (
            current is None
            or current.size_bytes != len(content_bytes)
            or current.sha256 != hashlib.sha256(content_bytes).hexdigest()
        ):
            current = self.index.compute_file_fingerprint(relative_path)

        if _is_binary(content_bytes):
            symbols: list[str] = []
            summary = "Binary or non-UTF-8 file; content was not indexed."
        else:
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                symbols = []
                summary = "Binary or non-UTF-8 file; content was not indexed."
            else:
                if language == "python":
                    symbols, summary = self.summarize_python(content)
                elif language == "markdown":
                    symbols, summary = self.summarize_markdown(content)
                else:
                    symbols, summary = self.summarize_text(content)

        return FileSummary(
            path=current.path,
            sha256=current.sha256,
            size_bytes=current.size_bytes,
            updated_at=current.updated_at,
            language=language,
            symbols=symbols,
            summary=_truncate(summary, self.max_summary_chars),
        )

    def summarize_python(self, content: str) -> tuple[list[str], str]:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            _, preview = self.summarize_text(content)
            return [], f"Python syntax could not be parsed. {preview}"

        classes = [
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        ]
        functions = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        symbols = [f"class {name}" for name in classes]
        symbols.extend(f"function {name}" for name in functions)

        parts = [
            f"Python module with {len(classes)} classes and "
            f"{len(functions)} module-level functions."
        ]
        if classes:
            parts.append(f"Classes: {', '.join(classes)}.")
        if functions:
            parts.append(f"Functions: {', '.join(functions)}.")
        docstring = ast.get_docstring(tree)
        if docstring:
            parts.append(f"Module purpose: {_single_line(docstring)}")
        return symbols, " ".join(parts)

    def summarize_markdown(self, content: str) -> tuple[list[str], str]:
        headings = [
            match.group(1).strip()
            for line in content.splitlines()
            if (match := _MARKDOWN_HEADING.match(line))
        ]
        symbols = [f"heading {heading}" for heading in headings]
        if headings:
            summary = (
                f"Markdown document with {len(headings)} headings: "
                f"{', '.join(headings)}."
            )
        else:
            _, preview = self.summarize_text(content)
            summary = f"Markdown document without headings. {preview}"
        return symbols, summary

    def summarize_text(self, content: str) -> tuple[list[str], str]:
        lines = [
            _single_line(line)
            for line in content.splitlines()
            if line.strip()
        ][: self.max_text_lines]
        if not lines:
            return [], "Empty text file."

        preview = " | ".join(lines)
        return [], f"Text preview: {preview}"


def _detect_language(path: Path) -> str:
    lower_name = path.name.lower()
    if lower_name == "dockerfile":
        return "dockerfile"
    if lower_name in {"makefile", "pipfile"}:
        return lower_name
    return LANGUAGES.get(path.suffix.lower(), "text")


def _is_binary(content: bytes) -> bool:
    return b"\0" in content[:8_192]


def _single_line(content: str) -> str:
    return " ".join(content.split())


def _truncate(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    marker = "... [truncated]"
    if max_chars <= len(marker):
        return marker[:max_chars]
    return content[: max_chars - len(marker)].rstrip() + marker
