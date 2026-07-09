"""Package and repository root resolution."""
from __future__ import annotations

import os
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.paths.names import find_package_root as _find_package_root


def find_package_root(start: Path) -> Path:
    """Walk up from start until a directory named 'audiagentic' is found.

    Delegates to the central resolver in foundation/paths/names.py.
    """
    return _find_package_root(start)


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
        if (candidate / "src" / "audiagentic").is_dir():
            return candidate

    package_parent = Path(__file__).resolve().parent.parent
    if (package_parent / "audiagentic").is_dir():
        return package_parent

    raise AudiaGenticError(
        code="CFG-PATHS-001",
        kind="paths",
        message=(
            f"Could not locate repository root from {anchor}. "
            "Set AUDIAGENTIC_REPO_ROOT or run inside an audiagentic checkout."
        ),
        details={"anchor": str(anchor)},
    )


REPO_ROOT: Path = find_repo_root()
SRC_ROOT: Path = REPO_ROOT / "src"
