"""Find Python unittest modules in a repository."""

from pathlib import Path


def discover_tests(root: str | Path) -> list[str]:
    root_path = Path(root)
    return sorted(path.name for path in root_path.glob("test_*.py"))
