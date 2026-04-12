"""Repository root and path resolution utilities.

Usage in any tool script:
    from tools.lib.repo_paths import REPO_ROOT, SRC_ROOT, TOOLS_ROOT, TESTS_ROOT

Root discovery does NOT require a git checkout. It resolves via a priority chain
so the tools work correctly in all environments: git checkouts, unpacked archives,
CI artifact extractions, pip installs, and Docker layers.

Resolution order
----------------
1. ``AUDIAGENTIC_REPO_ROOT`` environment variable — explicit override
2. ``.git`` directory marker — standard git checkout
3. ``pyproject.toml`` — installed/extracted package
4. Structural sentinel — directory contains both ``src/audiagentic`` and ``tools``

This separates the "find my root" concern from the "am I in a git repo" concern.
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
    # 1. Explicit environment variable override.
    env_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if env_root:
        candidate = Path(env_root).resolve()
        if candidate.is_dir():
            return candidate

    anchor = (start or Path(__file__)).resolve()
    candidates = [anchor, *anchor.parents]

    # 2. .git directory — standard git checkout.
    for candidate in candidates:
        if (candidate / ".git").is_dir():
            return candidate

    # 3. pyproject.toml — installed package or extracted archive.
    for candidate in candidates:
        if (candidate / "pyproject.toml").is_file():
            return candidate

    # 4. Structural sentinel — must contain src/audiagentic AND tools/.
    for candidate in candidates:
        if (
            (candidate / "src" / "audiagentic").is_dir()
            and (candidate / "tools").is_dir()
        ):
            return candidate

    raise RuntimeError(
        f"Could not locate repository root from {anchor}.\n"
        "Set the AUDIAGENTIC_REPO_ROOT environment variable to the repo root path, "
        "or ensure this file is inside an audiagentic checkout or package."
    )


REPO_ROOT: Path = find_repo_root()
SRC_ROOT: Path = REPO_ROOT / "src"
TESTS_ROOT: Path = REPO_ROOT / "tests"
TOOLS_ROOT: Path = REPO_ROOT / "tools"
DOCS_ROOT: Path = REPO_ROOT / "docs"
