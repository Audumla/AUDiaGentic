"""Package path resolution utilities."""
from __future__ import annotations

import os
import time
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError


def find_project_root(start: Path | None = None) -> Path | None:
    """Locate the project being operated on (the dir holding ``.audiagentic/``).

    Honors an explicit ``AUDIAGENTIC_REPO_ROOT`` override (needed when the
    package is installed somewhere other than the target project); otherwise
    walks up from ``start`` (default CWD) looking for the authoritative
    ``.audiagentic/`` marker. Bounded to 10 levels / 500ms so an odd mount can
    never hang the walk. Returns ``None`` if not found — callers that require a
    root raise on ``None``.
    """
    if env_root := os.environ.get("AUDIAGENTIC_REPO_ROOT"):
        return Path(env_root)
    deadline = time.monotonic() + 0.5
    current = (start or Path.cwd()).resolve()
    for _ in range(10):
        if time.monotonic() > deadline:
            break
        if (current / ".audiagentic").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


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
SRC_ROOT: Path = REPO_ROOT / "src" if (REPO_ROOT / "src" / "audiagentic").is_dir() else REPO_ROOT
