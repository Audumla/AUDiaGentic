"""Package path resolution utilities."""
from __future__ import annotations

import os
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """Locate repo root for dev/runtime tooling."""
    env_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if env_root:
        candidate = Path(env_root).resolve()
        if candidate.is_dir() and (
            (candidate / "pyproject.toml").is_file()
            or (candidate / "src" / "audiagentic").is_dir()
        ):
            return candidate

    anchor = (start or Path(__file__)).resolve()
    candidates = [anchor, *anchor.parents]

    for candidate in candidates:
        if (candidate / "pyproject.toml").is_file():
            return candidate

    for candidate in candidates:
        if (candidate / "src" / "audiagentic").is_dir():
            return candidate

    package_parent = Path(__file__).resolve().parent.parent
    if (package_parent / "audiagentic").is_dir():
        return package_parent

    raise RuntimeError(
        f"Could not locate repository root from {anchor}. "
        "Set AUDIAGENTIC_REPO_ROOT or run inside an audiagentic checkout."
    )


REPO_ROOT: Path = find_repo_root()
SRC_ROOT: Path = REPO_ROOT / "src" if (REPO_ROOT / "src" / "audiagentic").is_dir() else REPO_ROOT
