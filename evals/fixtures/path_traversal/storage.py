"""Resolve object names below a storage root."""

from pathlib import Path


def safe_join(root: str | Path, name: str) -> Path:
    root_path = Path(root).resolve()
    candidate = (root_path / name).resolve()
    if not str(candidate).startswith(str(root_path)):
        raise ValueError("path escapes storage root")
    return candidate
