"""Shared file-pattern matching for coding-LSP discovery and resolution."""
from __future__ import annotations

from pathlib import Path


def file_matches_patterns(
    file_path: Path,
    patterns: list[str] | tuple[str, ...],
) -> bool:
    """Match an extension such as ``.py`` or an exact basename such as ``Makefile``."""
    extension = file_path.suffix.lower()
    name = file_path.name.lower()
    for pattern in patterns:
        normalized = pattern.lower()
        if normalized.startswith("."):
            if extension == normalized:
                return True
        elif name == normalized:
            return True
    return False


__all__ = ["file_matches_patterns"]
