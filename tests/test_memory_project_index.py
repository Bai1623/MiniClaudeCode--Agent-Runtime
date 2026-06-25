"""Tests for project file discovery and fingerprints."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from miniclaudecode.memory import FileSummary, ProjectIndex


class TestProjectIndex(unittest.TestCase):
    def test_scan_recognizes_supported_files_and_filters_noise(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "src" / "app.py", "print('ok')")
            _write(root / "README.md", "# Project")
            _write(root / "pyproject.toml", "[project]")
            _write(root / "config.json", "{}")
            _write(root / "image.png", "not indexed")
            _write(root / ".env", "SECRET=value")
            _write(root / ".git" / "config", "ignored")
            _write(root / "__pycache__" / "app.py", "ignored")
            _write(root / ".miniclaudecode" / "traces" / "trace.json", "{}")
            _write(root / "venv" / "module.py", "ignored")

            fingerprints = ProjectIndex(root).scan()

            self.assertEqual(
                [item.path for item in fingerprints],
                ["README.md", "config.json", "pyproject.toml", "src/app.py"],
            )

    def test_get_tracked_files_respects_gitignore(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _run_git(root, "init")
            _write(root / ".gitignore", "ignored.py\n")
            _write(root / "tracked.py", "tracked = True")
            _write(root / "untracked.md", "# Included")
            _write(root / "ignored.py", "ignored = True")
            _run_git(root, "add", "tracked.py", ".gitignore")

            paths = ProjectIndex(root).get_tracked_files()

            self.assertEqual(
                [path.as_posix() for path in paths],
                ["tracked.py", "untracked.md"],
            )

    def test_git_scan_preserves_unicode_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _run_git(root, "init")
            _write(root / "文档" / "设计.md", "# 设计")
            _run_git(root, "add", "文档/设计.md")

            paths = ProjectIndex(root).get_tracked_files()

            self.assertEqual(
                [path.as_posix() for path in paths],
                ["文档/设计.md"],
            )

    def test_compute_file_fingerprint_is_stable_for_same_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "module.py", "value = 1\n")
            index = ProjectIndex(root)

            first = index.compute_file_fingerprint("module.py")
            second = index.compute_file_fingerprint(root / "module.py")

            self.assertEqual(first, second)
            self.assertEqual(first.size_bytes, (root / "module.py").stat().st_size)
            self.assertTrue(first.updated_at.endswith("Z"))

    def test_is_summary_stale_tracks_hash_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "module.py"
            _write(path, "value = 1\n")
            index = ProjectIndex(root)
            fingerprint = index.compute_file_fingerprint("module.py")
            summary = FileSummary(
                path=fingerprint.path,
                sha256=fingerprint.sha256,
                size_bytes=fingerprint.size_bytes,
                updated_at=fingerprint.updated_at,
                language="python",
                symbols=[],
                summary="Module.",
            )

            self.assertFalse(index.is_summary_stale(summary))
            _write(path, "value = 2\n")
            self.assertTrue(index.is_summary_stale(summary))

    def test_missing_summary_file_is_stale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = FileSummary(
                path="missing.py",
                sha256="missing",
                size_bytes=0,
                updated_at="2026-06-25T00:00:00Z",
                language="python",
                symbols=[],
                summary="Missing.",
            )

            self.assertTrue(ProjectIndex(tmpdir).is_summary_stale(summary))

    def test_fingerprint_rejects_path_outside_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "project"
            root.mkdir()
            outside = Path(tmpdir) / "outside.py"
            _write(outside, "value = 1")

            with self.assertRaisesRegex(ValueError, "outside project root"):
                ProjectIndex(root).compute_file_fingerprint(outside)

    def test_invalid_project_root_returns_clear_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing"

            with self.assertRaisesRegex(ValueError, "not a directory"):
                ProjectIndex(missing).get_tracked_files()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_git(root: Path, *args: str) -> None:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)


if __name__ == "__main__":
    unittest.main()
