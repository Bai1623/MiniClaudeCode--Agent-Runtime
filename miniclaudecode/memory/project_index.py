"""Deterministic project file discovery and fingerprinting."""

from __future__ import annotations

import hashlib
import locale
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from miniclaudecode.memory.records import FileSummary


DEFAULT_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".miniclaudecode",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "env",
        "node_modules",
        "venv",
    }
)
INDEXED_EXTENSIONS = frozenset(
    {
        ".cfg",
        ".css",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".py",
        ".rst",
        ".sh",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
)
INDEXED_FILENAMES = frozenset(
    {
        "dockerfile",
        "license",
        "makefile",
        "pipfile",
        "readme",
        "requirements.txt",
    }
)


@dataclass(frozen=True)
class FileFingerprint:
    path: str
    sha256: str
    size_bytes: int
    updated_at: str


class ProjectIndex:
    """Finds indexable project files and computes cache fingerprints."""

    def __init__(
        self,
        project_root: str | Path = ".",
        excluded_dirs: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.excluded_dirs = frozenset(
            DEFAULT_EXCLUDED_DIRS if excluded_dirs is None else excluded_dirs
        )

    def scan(self) -> list[FileFingerprint]:
        return [
            self.compute_file_fingerprint(path)
            for path in self.get_tracked_files()
        ]

    def get_tracked_files(self) -> list[Path]:
        self._ensure_root()
        git_files = self._get_git_files()
        candidates = git_files if git_files is not None else self._walk_files()
        return sorted(
            {
                path
                for path in candidates
                if self._is_indexable(path)
            },
            key=lambda path: path.as_posix(),
        )

    def compute_file_fingerprint(self, path: str | Path) -> FileFingerprint:
        relative_path, absolute_path = self._resolve_file(path)
        content = absolute_path.read_bytes()
        stat = absolute_path.stat()
        updated_at = datetime.fromtimestamp(
            stat.st_mtime,
            timezone.utc,
        ).isoformat().replace("+00:00", "Z")
        return FileFingerprint(
            path=relative_path.as_posix(),
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            updated_at=updated_at,
        )

    def is_summary_stale(self, summary: FileSummary) -> bool:
        try:
            fingerprint = self.compute_file_fingerprint(summary.path)
        except (FileNotFoundError, IsADirectoryError, ValueError):
            return True
        return (
            summary.sha256 != fingerprint.sha256
            or summary.size_bytes != fingerprint.size_bytes
        )

    def _ensure_root(self) -> None:
        if not self.project_root.is_dir():
            raise ValueError(f"Project root is not a directory: {self.project_root}")

    def _get_git_files(self) -> list[Path] | None:
        try:
            completed = subprocess.run(
                [
                    "git",
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "-z",
                ],
                cwd=self.project_root,
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

        if completed.returncode != 0:
            return None

        return [
            Path(_decode_git_path(item))
            for item in completed.stdout.split(b"\0")
            if item
        ]

    def _walk_files(self) -> list[Path]:
        files: list[Path] = []
        for root, dir_names, file_names in os.walk(
            self.project_root,
            followlinks=False,
        ):
            dir_names[:] = sorted(
                name
                for name in dir_names
                if name not in self.excluded_dirs
                and not (Path(root) / name).is_symlink()
            )
            root_path = Path(root)
            for file_name in sorted(file_names):
                absolute_path = root_path / file_name
                if not absolute_path.is_symlink():
                    files.append(absolute_path.relative_to(self.project_root))
        return files

    def _is_indexable(self, path: Path) -> bool:
        if path.is_absolute() or ".." in path.parts:
            return False
        if any(part in self.excluded_dirs for part in path.parts):
            return False
        if _is_sensitive_file(path.name):
            return False

        absolute_path = self.project_root / path
        if not absolute_path.is_file() or absolute_path.is_symlink():
            return False

        lower_name = path.name.lower()
        return (
            path.suffix.lower() in INDEXED_EXTENSIONS
            or lower_name in INDEXED_FILENAMES
        )

    def _resolve_file(self, path: str | Path) -> tuple[Path, Path]:
        candidate = Path(path)
        absolute_path = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.project_root / candidate).resolve()
        )
        try:
            relative_path = absolute_path.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError(
                f"File is outside project root: {absolute_path}"
            ) from exc
        if not absolute_path.is_file():
            raise FileNotFoundError(f"Project file not found: {absolute_path}")
        return relative_path, absolute_path


def _is_sensitive_file(file_name: str) -> bool:
    lower_name = file_name.lower()
    return lower_name == ".env" or lower_name.startswith(".env.")


def _decode_git_path(path: bytes) -> str:
    for encoding in ("utf-8", locale.getpreferredencoding(False), "gbk"):
        try:
            return path.decode(encoding)
        except UnicodeDecodeError:
            continue
    return path.decode("utf-8", errors="replace")
