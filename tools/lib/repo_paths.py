"""Repository root and path resolution utilities.

Usage in any tool script:
    from tools.lib.repo_paths import REPO_ROOT, SRC_ROOT, TOOLS_ROOT, TESTS_ROOT

This module resolves paths by walking up from the current file until it finds a
.git directory — the canonical repository root marker. This approach is robust
regardless of how deeply nested the calling script is, and requires no hardcoded
depth counts.
"""
from __future__ import annotations

from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from *start* until a .git directory is found.

    Parameters
    ----------
    start:
        Starting path for the search. Defaults to this file's location.

    Raises
    ------
    RuntimeError
        If no .git directory is found before reaching the filesystem root.
    """
    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").is_dir():
            return candidate
    raise RuntimeError(
        f"Could not locate repository root from {current}. "
        "Ensure this file is inside a git repository."
    )


REPO_ROOT: Path = find_repo_root()
SRC_ROOT: Path = REPO_ROOT / "src"
TESTS_ROOT: Path = REPO_ROOT / "tests"
TOOLS_ROOT: Path = REPO_ROOT / "tools"
DOCS_ROOT: Path = REPO_ROOT / "docs"
