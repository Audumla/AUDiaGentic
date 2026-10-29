"""Project root resolution — locate .audiagentic marker directory."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from audiagentic.foundation.paths.names import PROJECT_MARKER_NAME


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
        if (current / PROJECT_MARKER_NAME).exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def discover_checkout_root(start: Path | None = None) -> Path | None:
    """The git checkout containing ``start`` (default CWD), worktrees included.

    Used by settings resolution (docs/design/configuration-model.md): the
    project scope is the current checkout's tracked ``.audiagentic/``, so a
    fresh worktree needs no bootstrap. Never returns the git common directory.
    Uses ``git rev-parse --show-toplevel``; when git is missing or refuses the
    repository (for example "dubious ownership" in containers) it walks up to
    the nearest ``.git`` directory or file. ``None`` outside a repository.

    ``find_project_root`` (``.audiagentic`` marker) remains for existing
    callers until CFG04/CFG09 migrate them.
    """
    current = (start or Path.cwd()).resolve()
    git = shutil.which("git")
    if git is not None:
        try:
            completed = subprocess.run(
                [git, "rev-parse", "--show-toplevel"], cwd=current, capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            completed = None
        if completed is not None and completed.returncode == 0 and completed.stdout.strip():
            return Path(completed.stdout.strip()).resolve()
    for directory in (current, *current.parents):
        if (directory / ".git").exists():
            return directory
    return None
