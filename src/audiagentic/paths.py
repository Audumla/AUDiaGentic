"""Repository root and path resolution utilities.

Usage anywhere in the package or test suite:

    from audiagentic.paths import REPO_ROOT, SRC_ROOT, TESTS_ROOT

Root discovery does NOT require a git checkout. It resolves via a priority chain
so this works correctly in all environments: git checkouts, unpacked archives,
CI artifact extractions, pip installs, and Docker layers.

Resolution order
----------------
1. ``AUDIAGENTIC_REPO_ROOT`` environment variable — explicit override
2. ``.git`` directory marker — standard git checkout
3. ``pyproject.toml`` — installed/extracted package
4. Structural sentinel — directory contains both ``src/audiagentic`` and ``tests``
"""
from __future__ import annotations

import os
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """Locate the repository root using a multi-fallback strategy.

    Parameters
    ----------
    start:
        Starting path for the upward search. Defaults to this file's location.

    Returns
    -------
    Path
        Resolved absolute path to the repository root.

    Raises
    ------
    RuntimeError
        If no root can be found via any strategy.
    """
    env_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if env_root:
        candidate = Path(env_root).resolve()
        if candidate.is_dir():
            return candidate

    anchor = (start or Path(__file__)).resolve()
    candidates = [anchor, *anchor.parents]

    for candidate in candidates:
        if (candidate / ".git").is_dir():
            return candidate

    for candidate in candidates:
        if (candidate / "pyproject.toml").is_file():
            return candidate

    for candidate in candidates:
        if (
            (candidate / "src" / "audiagentic").is_dir()
            and (candidate / "tests").is_dir()
        ):
            return candidate

    raise RuntimeError(
        f"Could not locate repository root from {anchor}. "
        "Set the AUDIAGENTIC_REPO_ROOT environment variable to the repo root path, "
        "or ensure this file is inside an audiagentic checkout or package."
    )


REPO_ROOT: Path = find_repo_root()
SRC_ROOT: Path = REPO_ROOT / "src"
TESTS_ROOT: Path = REPO_ROOT / "tests"
DOCS_ROOT: Path = REPO_ROOT / "docs"
